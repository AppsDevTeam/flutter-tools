from PIL import Image
import os

source = os.path.join("src", "ui", "icon.png")
target = os.path.join("src", "ui", "icon.ico")

if os.path.exists(source):
    img = Image.open(source)
    # Uložíme jako ICO s více velikostmi, což Windows mají rády
    img.save(target, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"✅ Ikonka vytvořena: {target}")
else:
    print(f"❌ Zdroj {source} nenalezen!")