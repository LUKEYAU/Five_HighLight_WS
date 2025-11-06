import cv2
import os

# === 輸入影片路徑 ===
VIDEO_PATH = r"C:\Users\yauka\OneDrive\桌面\highlight.mp4"
OUTPUT_PATH = os.path.splitext(VIDEO_PATH)[0] + "_660x360.mp4"

# === 讀取影片 ===
cap = cv2.VideoCapture(VIDEO_PATH)

# 取得原始 FPS
fps = int(cap.get(cv2.CAP_PROP_FPS))

# 設定新的尺寸
new_width = 660
new_height = 360

# 影片編碼器設定
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps, (new_width, new_height))

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # 重新調整大小
    resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
    out.write(resized_frame)

cap.release()
out.release()
cv2.destroyAllWindows()

print(f"影片輸出完成: {OUTPUT_PATH}")
