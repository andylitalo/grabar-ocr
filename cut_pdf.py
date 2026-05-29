from pypdf import PdfReader, PdfWriter
import os                                                                                                         
                                                                                      
src = "data/Ժամագիրք ԱՏԵՆԻ.pdf"
out_dir = "data/pages"                                                                                            

reader = PdfReader(src)                                                                                           
total = len(reader.pages)                                                                                       
print(f"Total pages: {total}")

for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    out_path = os.path.join(out_dir, f"{i+1}.pdf")
    with open(out_path, "wb") as f:
        writer.write(f)

print("Done.")
