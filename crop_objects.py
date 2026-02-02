"""
Object Image Cropping Script
Crops object images to remove transparent padding, keeping only the actual object content.
"""

import os
from pathlib import Path

import yaml
from PIL import Image


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def crop_to_content(image: Image.Image, padding: int = 0) -> Image.Image:
    """
    Crop image to remove transparent padding around the actual content.
    
    Args:
        image: PIL Image to crop
        padding: Optional padding to add around the cropped content (in pixels)
    
    Returns:
        Cropped image containing only the non-transparent region (plus optional padding)
    """
    # Ensure image has alpha channel
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    
    # Get the alpha channel
    alpha = image.split()[3]
    
    # Get bounding box of non-transparent pixels
    bbox = alpha.getbbox()
    
    if bbox is None:
        # Image is fully transparent, return as-is
        print("  Warning: Image is fully transparent")
        return image
    
    # Add padding if specified
    if padding > 0:
        left, top, right, bottom = bbox
        width, height = image.size
        bbox = (
            max(0, left - padding),
            max(0, top - padding),
            min(width, right + padding),
            min(height, bottom + padding)
        )
    
    # Crop to the bounding box
    return image.crop(bbox)


def get_image_files(directory: str, extensions: tuple = (".png",)) -> list:
    """Get all image files from a directory."""
    if not os.path.exists(directory):
        raise FileNotFoundError(f"Directory not found: {directory}")
    
    files = []
    for f in os.listdir(directory):
        if f.lower().endswith(extensions):
            files.append(os.path.join(directory, f))
    return files


def main():
    # Load configuration
    config = load_config()
    
    # Get settings from config
    input_dir = config.get("object_dir", "data/objects")
    output_dir = config.get("cropped_object_dir", "data/objects_cropped")
    padding = config.get("crop_padding", 0)
    overwrite = config.get("crop_overwrite", False)
    
    # Determine output directory
    if overwrite:
        output_dir = input_dir
        print(f"Mode: Overwrite original files in {input_dir}")
    else:
        os.makedirs(output_dir, exist_ok=True)
        print(f"Mode: Save cropped files to {output_dir}")
    
    # Get object images
    object_files = get_image_files(input_dir, extensions=(".png",))
    
    if not object_files:
        print(f"No object images found in {input_dir}")
        return
    
    print(f"Found {len(object_files)} object images")
    print(f"Padding: {padding}px")
    print("-" * 50)
    
    processed = 0
    
    for obj_path in object_files:
        filename = Path(obj_path).name
        
        # Load image
        image = Image.open(obj_path)
        original_size = image.size
        
        # Crop to content
        cropped = crop_to_content(image, padding=padding)
        new_size = cropped.size
        
        # Calculate size reduction
        original_pixels = original_size[0] * original_size[1]
        new_pixels = new_size[0] * new_size[1]
        reduction = (1 - new_pixels / original_pixels) * 100 if original_pixels > 0 else 0
        
        # Save
        output_path = os.path.join(output_dir, filename)
        cropped.save(output_path, "PNG")
        
        print(f"  {filename}: {original_size[0]}x{original_size[1]} -> {new_size[0]}x{new_size[1]} ({reduction:.1f}% smaller)")
        processed += 1
    
    print("-" * 50)
    print(f"Processed {processed} images")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
