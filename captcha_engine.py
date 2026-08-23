"""
TWSE 驗證碼辨識雙引擎模組
優先級：
1. 專用 CNN 深度學習模型 (twse_cnn_model.hdf5 + OpenCV 預處理) - 辨識率 98%+
2. 通用 ddddocr 模型 (Fallback 備援) - 辨識率 88%~92%
"""

import os
import io
import re
from typing import Optional

# 抑制 TensorFlow 冗長 C++ 日誌
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
import warnings
warnings.filterwarnings("ignore")

# 專用 CNN 支援字元集
ALLOWED_CHARS = "ACDEFGHJKLNPQRTUVXYZ2346789"

# 優先尋找本目錄，其次尋找跨專案目錄
LOCAL_MODEL = os.path.join(os.path.dirname(__file__), "twse_cnn_model.hdf5")
REL_MODEL = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "auto_crawler_tw_stock",
        "TWSE_crawler",
        "twse_cnn_model.hdf5",
    )
)
MODEL_PATH = LOCAL_MODEL if os.path.exists(LOCAL_MODEL) else REL_MODEL

_cnn_model = None
_cnn_load_attempted = False
_ddddocr_instance = None


def _get_cnn_model():
    global _cnn_model, _cnn_load_attempted
    if not _cnn_load_attempted:
        _cnn_load_attempted = True
        if os.path.exists(MODEL_PATH):
            try:
                try:
                    from tensorflow.keras.models import load_model
                except ImportError:
                    from keras.models import load_model

                # 使用 compile=False 避免舊版優化器相容問題
                model = load_model(MODEL_PATH, compile=False)
                _cnn_model = model
                print("[*] 成功載入專用 TWSE CNN 驗證碼模型 (辨識率 98%+)")
            except Exception as e:
                print(f"[!] 專用 CNN 模型載入失敗 ({e})，切換至 ddddocr 備用引擎")
                _cnn_model = None
        else:
            print("[!] 未找到 twse_cnn_model.hdf5，切換至 ddddocr 備用引擎")
    return _cnn_model


def _get_ddddocr():
    global _ddddocr_instance
    if _ddddocr_instance is None:
        try:
            import ddddocr

            _ddddocr_instance = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            print(f"[!] ddddocr 初始化失敗: {e}")
    return _ddddocr_instance


def _one_hot_decoding(prediction, allowed_chars=ALLOWED_CHARS) -> str:
    import numpy as np

    result = []
    # prediction shape: (1, 5, 27) 或類似多字元維度
    if len(prediction.shape) == 3:
        for char_pred in prediction[0]:
            idx = int(np.argmax(char_pred))
            if idx < len(allowed_chars):
                result.append(allowed_chars[idx])
    elif len(prediction.shape) == 2:
        for char_pred in prediction:
            idx = int(np.argmax(char_pred))
            if idx < len(allowed_chars):
                result.append(allowed_chars[idx])
    return "".join(result)


def _preprocess_image_cv2(img_bytes: bytes):
    """
    OpenCV 驗證碼前處理
    """
    import cv2
    import numpy as np

    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None

    # 調整大小以符合 CNN 輸入尺寸 (若需 150x50 或原尺寸)
    # 通常模型預設尺寸如 auto_crawler preprocessBatch.py
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY_INV)
    return img


def recognize_captcha(img_bytes: bytes) -> Optional[str]:
    """
    辨識 TWSE 5 碼圖形驗證碼
    """
    if not img_bytes:
        return None

    # 1. 嘗試使用專用 CNN 模型
    cnn = _get_cnn_model()
    if cnn is not None:
        try:
            import cv2
            import numpy as np

            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                train_data = np.stack([np.array(img) / 255.0])
                pred = cnn.predict(train_data, verbose=0)
                code = _one_hot_decoding(pred, ALLOWED_CHARS)
                code = re.sub(r"[^A-Za-z0-9]", "", code).strip().upper()
                if len(code) == 5:
                    return code
        except Exception:
            pass

    # 2. 備援：使用 ddddocr
    ocr = _get_ddddocr()
    if ocr is not None:
        try:
            code = ocr.classification(img_bytes)
            code = re.sub(r"[^A-Za-z0-9]", "", str(code)).strip().upper()
            return code
        except Exception:
            pass

    return None
