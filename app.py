import io
import logging
import os
import re
import time
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, ImageOps, UnidentifiedImageError

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """你是一個精準的文字轉錄與 OCR 工具。
請完整轉錄圖片中的主要本文，保留原始文字、符號與段落，不摘要、不改寫。
忽略社群平台及系統介面雜訊。只輸出轉錄結果，不要加入說明或 Markdown 格式。
原文中的 Markdown 符號、標籤、底線及其他符號都必須保留。
若圖片沒有可辨識的主要本文，請只輸出「（未辨識到文字）」；不確定的文字請標示「[無法辨識]」，不要臆測。"""
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_DIMENSION = 3072
LONG_IMAGE_RATIO = 3
MAX_IMAGE_PIXELS = 80_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def image_parts(image_input, split_long=False):
    """讀取並視需要分段處理圖片，保留各段原有順序。"""
    path = image_input.get("name") if isinstance(image_input, dict) else str(image_input)
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        segments = []
        if split_long and height > width * LONG_IMAGE_RATIO:
            segment_height = width * LONG_IMAGE_RATIO
            for top in range(0, height, segment_height):
                segments.append(image.crop((0, top, width, min(top + segment_height, height))))
        else:
            segments.append(image)
        parts = []
        for segment in segments:
            segment.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            segment.save(buffer, format="PNG", optimize=True)
            parts.append(types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/png"))
        return parts


def describe_error(error):
    """將常見錯誤轉成可採取行動的訊息，避免顯示原始請求內容。"""
    message = str(error).lower()
    code = getattr(error, "code", None)
    if code == 429 or "429" in message or "resource_exhausted" in message:
        return "API 額度或速率限制，請稍後再試或檢查帳戶額度。"
    if code in (401, 403) or any(value in message for value in ("401", "403", "api key", "permission_denied", "unauthenticated")):
        return "API Key 無效或沒有權限，請檢查金鑰及模型存取權限。"
    if code == 404 or "404" in message or "not_found" in message:
        return "找不到指定模型，或此模型不支援目前的 API；請更換模型。"
    if code in (500, 502, 503, 504) or any(value in message for value in ("500", "502", "503", "504", "unavailable", "timeout", "connection")):
        return "網路連線或服務暫時發生問題，請稍後重試。"
    return "擷取失敗，請檢查圖片、模型名稱及網路連線後重試。"


def extract_segment(client, part, instruction, models):
    last_error = None
    for model in models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[part, instruction],
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.0),
                )
                text = response.text
                if text and text.strip():
                    return text.strip(), model
                last_error = ValueError("empty response")
                break
            except Exception as error:
                last_error = error
                message = str(error).lower()
                code = getattr(error, "code", None)
                transient = code in (429, 500, 502, 503, 504) or any(
                    value in message for value in ("429", "500", "502", "503", "504", "resource_exhausted", "unavailable", "timeout", "connection")
                )
                if transient and attempt == 0:
                    time.sleep(1)
                    continue
                break
    if isinstance(last_error, ValueError) and str(last_error) == "empty response":
        raise RuntimeError("模型回傳空白結果，可能受到內容限制或服務狀態影響；請更換模型或重試。")
    raise RuntimeError(describe_error(last_error))


def process_input(api_key_input, text_input, image_inputs, model_input, fallback_input, split_long):
    api_key = (api_key_input or "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "❌ 找不到 API Key。請輸入金鑰或在 .env 設定 GEMINI_API_KEY。"
    if not image_inputs:
        return "⚠️ 請上傳至少一張圖片。文字欄位用於補充圖片辨識說明。"
    models = list(dict.fromkeys(name.strip() for name in [model_input, *(fallback_input or "").split(",")] if name and name.strip()))
    if not models:
        return "⚠️ 請輸入至少一個模型名稱。"
    try:
        client = genai.Client(api_key=api_key)
    except Exception as error:
        logger.warning("建立 API 用戶端失敗：%s", type(error).__name__)
        return "❌ 無法建立 API 連線，請檢查 API Key 與設定。"

    instruction = "請轉錄這張圖片的主要本文。"
    if text_input and text_input.strip():
        instruction += "\n使用者補充說明：\n" + text_input.strip()
    results = []
    for index, image_input in enumerate(image_inputs, start=1):
        path = image_input.get("name", "圖片") if isinstance(image_input, dict) else str(image_input)
        filename = Path(path).name
        try:
            parts = image_parts(image_input, split_long)
            segments = []
            for number, part in enumerate(parts, start=1):
                try:
                    text, _ = extract_segment(client, part, instruction, models)
                    segments.append(text)
                except Exception as error:
                    segments.append(f"❌ 第 {number} 段擷取失敗：{error}")
            results.append(f"--- 圖片 {index}：{filename} ---\n" + "\n\n".join(segments))
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            logger.warning("圖片處理失敗：%s", type(error).__name__)
            results.append(f"--- 圖片 {index}：{filename} ---\n❌ 無法讀取圖片，檔案可能損毀或尺寸過大。")
        except Exception as error:
            logger.warning("圖片處理失敗：%s", type(error).__name__)
            results.append(f"--- 圖片 {index}：{filename} ---\n❌ 圖片處理失敗，請更換檔案或重試。")
    return "\n\n".join(results)


def clean_formatting(text):
    """依使用者要求移除常見的行首 Markdown 格式。"""
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text or "")
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)
    return text


with gr.Blocks(title="Gemini 原始文字擷取 Agent") as demo:
    gr.Markdown("# 📝 Gemini 原始文字擷取 Agent")
    gr.Markdown("逐張擷取圖片主要本文並保留原文符號；圖片會傳送至 Gemini API。")
    api_key_input = gr.Textbox(label="Gemini API Key（選填）", placeholder="若 .env 已設定可留空", type="password")
    with gr.Row():
        with gr.Column():
            image_inputs = gr.Files(label="上傳圖片（依選取順序處理）", file_types=["image"])
            text_input = gr.Textbox(lines=3, label="補充辨識說明（選填）")
            model_input = gr.Textbox(label="主要模型", value=DEFAULT_MODEL)
            fallback_input = gr.Textbox(label="備援模型（選填，以逗號分隔）", placeholder="例如：其他有權使用的模型名稱")
            split_long = gr.Checkbox(label="將直式長截圖分段處理", value=False)
            gr.Markdown("長截圖分段可能在切割處截斷文字，並增加 API 請求次數、耗時與費用；建議核對結果。單張失敗時可重新上傳該圖片重試。")
            submit_btn = gr.Button("🚀 擷取原始文字", variant="primary")
        with gr.Column():
            output_text = gr.Textbox(lines=20, label="擷取結果（包含圖片名稱與狀態）")
            with gr.Row():
                copy_btn = gr.Button("📋 複製結果")
                clean_btn = gr.Button("移除行首 Markdown 格式")
    gr.HTML('<div style="text-align:center;margin-top:30px;color:#888;">CYX STUDIO</div>')
    submit_btn.click(process_input, inputs=[api_key_input, text_input, image_inputs, model_input, fallback_input, split_long], outputs=output_text)
    clean_btn.click(clean_formatting, inputs=output_text, outputs=output_text)
    copy_btn.click(fn=None, inputs=output_text, outputs=None, js="(text) => navigator.clipboard.writeText(text)")

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)
