import os
# --- DEPLOYMENT FIX ---
# Forces LangFlow to use a writeable folder for its database
os.environ["LANGFLOW_DIR"] = "/tmp/langflow_store"

import streamlit as st
from langflow.load import run_flow_from_json
import re
import requests
import textwrap
import time
import urllib.parse
import random 
from PIL import Image, ImageOps, ImageDraw, ImageFont
from io import BytesIO

# --- CONFIGURATION ---
FLOW_FILENAME = "Comic_Flow.json" 

st.set_page_config(page_title="AI Comic Studio", page_icon="💥", layout="wide")

# --- HELPER: GET FONT ---
@st.cache_resource
def get_comic_font(size=40):
    font_name = "ComicNeue-Bold.ttf"
    # Try local first
    if os.path.exists(font_name):
        try: return ImageFont.truetype(font_name, size)
        except: pass
    
    # Try /tmp (for cloud)
    tmp_font_path = "/tmp/ComicNeue-Bold.ttf"
    if not os.path.exists(tmp_font_path):
        try:
            url = "https://github.com/google/fonts/raw/main/ofl/comicneue/ComicNeue-Bold.ttf"
            response = requests.get(url)
            with open(tmp_font_path, "wb") as f:
                f.write(response.content)
        except: pass
    
    try: return ImageFont.truetype(tmp_font_path, size)
    except: return ImageFont.load_default()

# --- COMIC ENGINE ---
def create_comic_panel(img_url, caption_text, panel_index=0):
    # 1. CLEAN & RANDOMIZE URL
    # We strip old params and add a fresh seed to guarantee unique images
    if "pollinations" in img_url:
        img_url = img_url.split('?')[0] # Remove old query params
    
    # Check for bad/fake links and regenerate
    if not img_url or "example.com" in img_url or "placeholder" in img_url or not img_url.startswith("http"):
        print(f"Fixing broken link for: {caption_text}")
        encoded_caption = urllib.parse.quote(caption_text + " comic book style")
        img_url = f"https://image.pollinations.ai/prompt/{encoded_caption}"
    
    # Add unique seed and settings
    seed = random.randint(0, 100000) + (panel_index * 999)
    final_url = f"{img_url}?nologo=true&seed={seed}&width=1024&height=1024"

    # 2. DOWNLOAD (With Browser Headers)
    # This headers dict makes the request look like a real browser to avoid blocks
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    for attempt in range(3):
        try:
            response = requests.get(final_url, headers=headers, timeout=15) 
            response.raise_for_status() 
            
            img = Image.open(BytesIO(response.content)).convert("RGB")
            target_width = 1024
            target_height = 1024
            img = img.resize((target_width, target_height))
            
            # 3. DRAW CAPTION
            overlay = Image.new('RGBA', img.size, (0,0,0,0))
            draw = ImageDraw.Draw(overlay)
            font = get_comic_font(size=45)
            
            clean_caption = caption_text.replace("*", "").replace('"', '').strip()
            if not clean_caption: clean_caption = "..."
            lines = textwrap.wrap(clean_caption, width=40)
            
            box_height = (len(lines) * 55) + 40
            box_y = target_height - box_height - 20
            
            # Semi-transparent background for text
            draw.rectangle([(20, box_y), (target_width - 20, target_height - 20)], fill=(255, 255, 255, 230), outline="black", width=3)
            
            img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
            draw = ImageDraw.Draw(img)
            
            text_y = box_y + 20
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
                x_pos = (target_width - text_width) / 2
                draw.text((x_pos, text_y), line, font=font, fill="black")
                text_y += 55
                
            return ImageOps.expand(img, border=10, fill='black')
            
        except Exception as e:
            time.sleep(1)
            if attempt == 2: 
                print(f"Failed to load: {final_url} | Error: {e}")
                return None

# --- UI ---
st.title("💥 Agentic Comic Studio")

with st.sidebar:
    st.header("🎬 Director's Chair")
    char_desc = st.text_area("Character Bible:", "A cyberpunk girl with neon blue hair.")
    story = st.text_area("Next Episode Idea:", "She finds a glowing mysterious microchip.")
    generate_btn = st.button("✨ Filming New Episode", type="primary")
    
    if st.button("🗑️ Clear History (Fix Errors)"):
        st.session_state['episodes'] = []
        st.rerun()

if 'episodes' not in st.session_state: st.session_state['episodes'] = []

# --- MAIN LOGIC ---
if generate_btn:
    with st.spinner("🤖 Filming..."):
        try:
            strict_prompt = f"""
            STORY: {story}
            RULES:
            1. Create 3 panels.
            2. CALL 'generate_image' for EACH panel.
            3. OUTPUT FORMAT:
            PANEL 1
            Text: [Dialogue]
            ![Image]([URL])
            PANEL 2
            Text: [Dialogue]
            ![Image]([URL])
            """

            tweaks = {
                "Prompt Template-xxxxx": {
                    "character_description": char_desc,
                    "user_input": strict_prompt
                }
            }
            
            result = run_flow_from_json(
                flow=FLOW_FILENAME, 
                input_value=strict_prompt, 
                tweaks=tweaks, 
                session_id="comic-session-user-1", 
                fallback_to_env_vars=True
            )
            
            try: raw_text = result[0].outputs[0].results['message'].text
            except: raw_text = str(result)
            
            panels = []
            chunks = re.split(r'(?:\*\*|#)?\s*PANEL\s+\d+[:\.]*\s*(?:\*\*|#)?', raw_text, flags=re.IGNORECASE)
            
            for chunk in chunks:
                if not chunk.strip(): continue
                text_match = re.search(r'(?:Text|Caption|Dialogue)\s*[:\-]?\s*(.*?)(?=\n|!\[|http)', chunk, re.IGNORECASE | re.DOTALL)
                caption = text_match.group(1).strip() if text_match else "..."
                
                img_match = re.search(r'(?:\!\[.*?\]\((.*?)\)|(https?://\S+))', chunk)
                img_url = img_match.group(1) or img_match.group(2) if img_match else "https://example.com/placeholder.png"
                panels.append((img_url, caption))
            
            if panels:
                st.session_state['episodes'].append({"title": f"Episode {len(st.session_state['episodes'])+1}", "desc": story, "panels": panels})
            else:
                st.warning("Parsing failed. Raw output:")
                st.write(raw_text)

        except Exception as e:
            st.error(f"Error: {e}")

# --- RENDER FEED ---
if st.session_state['episodes']:
    for ep in st.session_state['episodes'][::-1]:
        st.markdown(f"### {ep['title']}")
        cols = st.columns(len(ep['panels']))
        for idx, (url, text) in enumerate(ep['panels']):
            with cols[idx]:
                final_img = create_comic_panel(url, text, panel_index=idx)
                if final_img:
                    st.image(final_img, use_container_width=True)
                else:
                    st.error("Image unavailable")
                    st.markdown(f"[Try Link Manually]({url})")
        st.divider()
