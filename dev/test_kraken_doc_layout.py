import os
from pathlib import Path
from PIL import Image, ImageDraw
import pypdfium2 as pdfium

from kraken import binarization, blla, pageseg
from kraken.lib import segmentation, vgsl

MODEL_PATH = "/Users/andylitalo/Library/Application Support/htrmopo/97665cf3-f83d-5594-8855-f28d3af9df7a/blla.mlmodel"
PAGES = [448, 530, 546, 551, 552, 555, 557, 564, 641]

def process_document(file_path: str, output_dir: str):
    """
    Accepts either a PDF or an Image file path.
    Extracts pages, breaks layout down, and dumps cropped text lines as JPEGs.
    """
    file_path = Path(file_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # --- 1. Handle PDF Input vs. Standard Image Input ---
    pages_to_process = []
    
    if file_path.suffix.lower() == '.pdf':
        print(f"📄 Processing PDF: {file_path.name}")
        pdf = pdfium.PdfDocument(str(file_path))
        for page_idx in range(len(pdf)):
            page = pdf[page_idx]
            # Render page to high-res PIL image (300 DPI is standard for historical texts)
            bitmap = page.render(scale=300/72) 
            pil_img = bitmap.to_pil()
            pages_to_process.append((pil_img, f"page_{page_idx + 1:03d}"))
    else:
        print(f"🖼️ Processing Image: {file_path.name}")
        try:
            pil_img = Image.open(file_path)
            # Ensure it is RGB for processing
            if pil_img.mode != 'RGB':
                pil_img = pil_img.convert('RGB')
            pages_to_process.append((pil_img, file_path.stem))
        except Exception as e:
            print(f"Skipping {file_path.name}: Not a valid image file. Error: {e}")
            return

    # --- 2. Process Each Page for Layout & Line Slicing ---
    for img, page_label in pages_to_process:
        print(f"  └─ Analyzing layout for {page_label}...")
        
        # Binarize (Kraken's nlbin adapts brilliantly to old parchment and prevents artifact bleed)
        bw_img = binarization.nlbin(img)
        
        # Extract baselines and layout polygons
        # Kraken ignores non-text decorative margins natively with the default model
        try:
            # Load the neural segmentation model you just pulled
            seg_model = vgsl.TorchVGSLModel.load_model(MODEL_PATH)

            # Then pass it directly to the segmenter inside your page loop
            bw_img = binarization.nlbin(img)
            layout = blla.segment(bw_img, model=seg_model)

        except Exception as e:
            print(f"     ❌ Failed to segment {page_label}: {e}")
            continue
            
        print(f"     ✓ Found {len(layout.lines)} valid text lines. Slicing...")

        # Create a blank slate canvas over a copy of the source page for debug visualization
        overlay_img = img.copy()
        draw = ImageDraw.Draw(overlay_img)

# --- 3. Crop and Save Individual Lines ---
        for line_idx, line in enumerate(layout.lines):
            try:
                line_filename = output_dir / f"{page_label}_line_{line_idx + 1:03d}.jpg"
                
                # Check if we have a legacy bounding box
                if hasattr(line, 'bounds'):
                    line_crop = img.crop(line.bounds)

                    # Visual Verification: Draw flat bounding rectangle in red
                    # line.bounds format is [xmin, ymin, xmax, ymax]
                    draw.rectangle(line.bounds, outline="red", width=2)
                    
                # If we have a modern neural baseline line
                else:
                    # Create a temporary single-line container that preserves the expected attributes
                    from copy import copy
                    single_line_layout = copy(layout)
                    single_line_layout.lines = [line]
                    
                    # Pass the proper container object directly
                    extracted_lines = list(segmentation.extract_polygons(img, single_line_layout))
                    if not extracted_lines:
                        continue
                    line_crop, _ = extracted_lines[0]

                    # Visual Verification: Map complex polygon coordinates
                    # line.boundary is a list of points [(x1, y1), (x2, y2), ...]
                    if hasattr(line, 'boundary') and line.boundary:
                        # Flattening coordinate lists isn't required by modern PIL, passing raw tuples works:
                        draw.polygon(line.boundary, outline="red", width=2)
                
                # Save the cropped line slice
                line_crop.save(line_filename, "JPEG", quality=95)
                
            except Exception as e:
                print(f"     ⚠️ Error cutting line {line_idx + 1}: {e}")
                continue

        # --- 4. Save the Final Diagnostics Page ---
        overlay_filename = output_dir / f"{page_label}_overlay.jpg"
        overlay_img.save(overlay_filename, "JPEG", quality=85)
        print(f"     📸 Diagnostic overlay saved: {overlay_filename.name}")

    print(f"✨ Finished processing {file_path.name}. All extracted lines saved to: {output_dir}\n")

# --- Execution Example ---
if __name__ == "__main__":
    print("Processing PDF...")
    for page in PAGES:
        output_dir = f"./segmented_lines/page_{page}/"
        os.makedirs(output_dir, exist_ok=True)
        process_document(
            file_path=f"/Users/andylitalo/church/grabar-ocr/data/pages/{page}.pdf", 
            output_dir=output_dir
        )
    print("PDF processed successfully")