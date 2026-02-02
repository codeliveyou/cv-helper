"""
Image Compositing Script
Adds object images to background images and generates labelme annotations.
"""

import os
import json
import base64
import random
from pathlib import Path
from io import BytesIO

import yaml
from PIL import Image


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_image_files(directory: str, extensions: tuple = (".jpg", ".jpeg", ".png")) -> list:
    """Get all image files from a directory."""
    if not os.path.exists(directory):
        raise FileNotFoundError(f"Directory not found: {directory}")
    
    files = []
    for f in os.listdir(directory):
        if f.lower().endswith(extensions):
            files.append(os.path.join(directory, f))
    return files


def crop_and_resize_to_target(image: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """
    Crop and resize image to target resolution while preserving aspect ratio.
    If the aspect ratio doesn't match, crop the center portion first, then resize.
    """
    target_ratio = target_width / target_height
    img_width, img_height = image.size
    img_ratio = img_width / img_height
    
    if abs(img_ratio - target_ratio) < 0.001:
        # Aspect ratio matches, just resize
        return image.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    # Need to crop first
    if img_ratio > target_ratio:
        # Image is wider, crop width
        new_width = int(img_height * target_ratio)
        left = (img_width - new_width) // 2
        image = image.crop((left, 0, left + new_width, img_height))
    else:
        # Image is taller, crop height
        new_height = int(img_width / target_ratio)
        top = (img_height - new_height) // 2
        image = image.crop((0, top, img_width, top + new_height))
    
    # Now resize to target
    return image.resize((target_width, target_height), Image.Resampling.LANCZOS)


def resize_object_with_height(obj_image: Image.Image, target_height: int) -> Image.Image:
    """
    Resize object image to target height while preserving aspect ratio.
    """
    obj_width, obj_height = obj_image.size
    ratio = target_height / obj_height
    new_width = int(obj_width * ratio)
    return obj_image.resize((new_width, target_height), Image.Resampling.LANCZOS)


def calculate_valid_position(obj_width: int, obj_height: int, config: dict) -> tuple:
    """
    Calculate a valid (x, y) position for the object center.
    Constraints:
    - 320 <= center_x <= 960
    - center_y <= 360
    - Object must fit within the image bounds (1280x720)
    """
    output_width = config["output_width"]
    output_height = config["output_height"]
    x_min = config["object_x_min"]
    x_max = config["object_x_max"]
    y_max = config["object_y_max"]
    
    # Calculate valid range for center position
    # Object must fit within image bounds
    half_width = obj_width // 2
    half_height = obj_height // 2
    
    # Adjust x range to ensure object fits
    valid_x_min = max(x_min, half_width)
    valid_x_max = min(x_max, output_width - half_width)
    
    # Adjust y range to ensure object fits
    valid_y_min = half_height  # Object top edge at y=0
    valid_y_max = min(y_max, output_height - half_height)
    
    if valid_x_min > valid_x_max or valid_y_min > valid_y_max:
        # Fallback: place at center of valid area
        center_x = (x_min + x_max) // 2
        center_y = y_max // 2
        return center_x, center_y
    
    center_x = random.randint(valid_x_min, valid_x_max)
    center_y = random.randint(valid_y_min, valid_y_max)
    
    return center_x, center_y


def composite_images(background: Image.Image, obj_image: Image.Image, center_x: int, center_y: int) -> Image.Image:
    """
    Composite object image onto background at the specified center position.
    """
    # Ensure background is in RGBA mode for compositing
    if background.mode != "RGBA":
        background = background.convert("RGBA")
    
    # Ensure object has alpha channel
    if obj_image.mode != "RGBA":
        obj_image = obj_image.convert("RGBA")
    
    obj_width, obj_height = obj_image.size
    
    # Calculate top-left position from center
    left = center_x - obj_width // 2
    top = center_y - obj_height // 2
    
    # Create a copy of background to paste onto
    result = background.copy()
    
    # Paste object with alpha mask
    result.paste(obj_image, (left, top), obj_image)
    
    # Convert back to RGB for output
    return result.convert("RGB")


def generate_random_filename(prefix: str, digits: int = 8) -> str:
    """Generate a random filename with prefix and random digits."""
    max_num = 10 ** digits - 1
    random_num = random.randint(0, max_num)
    return f"{prefix}-{random_num:0{digits}d}"


def image_to_base64(image: Image.Image, format: str = "JPEG", quality: int = 95) -> str:
    """Convert PIL Image to base64 string."""
    buffer = BytesIO()
    if format.upper() == "JPEG":
        image.save(buffer, format="JPEG", quality=quality)
    else:
        image.save(buffer, format=format)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def create_labelme_json(
    image: Image.Image,
    image_filename: str,
    label: str,
    bbox_left: float,
    bbox_top: float,
    bbox_right: float,
    bbox_bottom: float,
    image_format: str = "JPEG",
    jpg_quality: int = 95
) -> dict:
    """
    Create labelme format JSON annotation.
    """
    return {
        "version": "5.5.0",
        "flags": {},
        "shapes": [
            {
                "label": label,
                "points": [
                    [bbox_left, bbox_top],
                    [bbox_right, bbox_bottom]
                ],
                "group_id": None,
                "description": "",
                "shape_type": "rectangle",
                "flags": {},
                "mask": None
            }
        ],
        "imagePath": image_filename,
        "imageData": image_to_base64(image, format=image_format, quality=jpg_quality),
        "imageHeight": image.height,
        "imageWidth": image.width
    }


def main():
    # Load configuration
    config = load_config()
    
    # Create output directories (separate for images and json)
    output_dir = config["output_dir"]
    output_images_dir = os.path.join(output_dir, "images")
    output_json_dir = os.path.join(output_dir, "json")
    os.makedirs(output_images_dir, exist_ok=True)
    os.makedirs(output_json_dir, exist_ok=True)
    
    # Get background and object images
    background_files = get_image_files(
        config["background_dir"],
        extensions=(".jpg", ".jpeg", ".png")
    )
    object_files = get_image_files(
        config["object_dir"],
        extensions=(".png",)
    )
    
    if not background_files:
        print(f"No background images found in {config['background_dir']}")
        return
    
    if not object_files:
        print(f"No object images found in {config['object_dir']}")
        return
    
    print(f"Found {len(background_files)} background images")
    print(f"Found {len(object_files)} object images")
    
    duplicate_count = config["background_duplicate_count"]
    min_height = config["min_object_height"]
    max_height = config["max_object_height"]
    target_width = config["output_width"]
    target_height = config["output_height"]
    label = config["object_label"]
    output_prefix = config.get("output_prefix", "gen")
    output_format = config.get("output_format", "jpg").lower()
    jpg_quality = config.get("output_jpg_quality", 95)
    
    # Determine image format settings
    if output_format == "jpg":
        image_ext = ".jpg"
        pil_format = "JPEG"
    else:
        image_ext = ".png"
        pil_format = "PNG"
    
    total_generated = 0
    
    for bg_path in background_files:
        bg_name = Path(bg_path).stem
        print(f"\nProcessing background: {bg_name}")
        
        # Load and prepare background
        background = Image.open(bg_path)
        background = crop_and_resize_to_target(background, target_width, target_height)
        
        # Select random object images for this background
        selected_objects = random.choices(object_files, k=duplicate_count)
        
        for i, obj_path in enumerate(selected_objects):
            obj_name = Path(obj_path).stem
            
            # Load object image
            obj_image = Image.open(obj_path)
            
            # Resize object to random height within range
            target_obj_height = random.randint(min_height, max_height)
            obj_resized = resize_object_with_height(obj_image, target_obj_height)
            
            # Calculate valid position
            center_x, center_y = calculate_valid_position(
                obj_resized.width, obj_resized.height, config
            )
            
            # Composite images
            result = composite_images(background.copy(), obj_resized, center_x, center_y)
            
            # Calculate bounding box
            obj_width, obj_height = obj_resized.size
            bbox_left = center_x - obj_width // 2
            bbox_top = center_y - obj_height // 2
            bbox_right = bbox_left + obj_width
            bbox_bottom = bbox_top + obj_height
            
            # Generate output filename with random 8-digit number
            output_name = generate_random_filename(output_prefix, digits=8)
            output_image_filename = f"{output_name}{image_ext}"
            output_image_path = os.path.join(output_images_dir, output_image_filename)
            output_json_path = os.path.join(output_json_dir, f"{output_name}.json")
            
            # Save output image
            if pil_format == "JPEG":
                result.save(output_image_path, pil_format, quality=jpg_quality)
            else:
                result.save(output_image_path, pil_format)
            
            # Create and save labelme JSON
            # imagePath is relative path from json directory to image
            relative_image_path = f"../images/{output_image_filename}"
            labelme_data = create_labelme_json(
                result,
                relative_image_path,
                label,
                float(bbox_left),
                float(bbox_top),
                float(bbox_right),
                float(bbox_bottom),
                image_format=pil_format,
                jpg_quality=jpg_quality
            )
            
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(labelme_data, f, indent=2)
            
            print(f"  Generated: {output_image_filename} (object: {obj_name}, "
                  f"center: ({center_x}, {center_y}), height: {target_obj_height}px)")
            
            total_generated += 1
    
    print(f"\n{'='*50}")
    print(f"Total images generated: {total_generated}")
    print(f"Output images: {output_images_dir}")
    print(f"Output json: {output_json_dir}")


if __name__ == "__main__":
    main()
