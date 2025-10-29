"""
Script to examine PowerPoint template structure
"""
from pptx import Presentation
import os

def examine_template(template_path):
    """Examine the PowerPoint template structure"""
    prs = Presentation(template_path)

    print(f"Template: {template_path}")
    print(f"Total slides: {len(prs.slides)}")
    print("\n" + "="*80 + "\n")

    for idx, slide in enumerate(prs.slides):
        print(f"Slide {idx + 1}:")
        print(f"  Layout: {slide.slide_layout.name}")
        print(f"  Shapes: {len(slide.shapes)}")

        for shape_idx, shape in enumerate(slide.shapes):
            print(f"    Shape {shape_idx + 1}: {shape.shape_type} - {shape.name}")

            # If it has text
            if hasattr(shape, "text"):
                text_preview = shape.text[:50].replace('\n', ' ') if shape.text else ""
                if text_preview:
                    print(f"      Text: {text_preview}...")

            # If it's a placeholder
            if hasattr(shape, "is_placeholder") and shape.is_placeholder:
                print(f"      Placeholder type: {shape.placeholder_format.type}")

        print()

if __name__ == "__main__":
    template_path = r"C:\Users\gklb\PycharmProjects\AI_Reporter\src\data\config\template.pptx"
    examine_template(template_path)
