VERSION = "0.07"

from flask import Flask, request, jsonify, Response, send_file
from flask_cors import CORS
import subprocess
import os
import glob
import re
import shutil

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = os.path.expanduser("~/storage/downloads/InstaGet")
COMPILATIONS_DIR = os.path.join(DOWNLOAD_DIR, "compilations")
COOKIES_FILE = os.path.expanduser("~/instagram_cookies.txt")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(COMPILATIONS_DIR, exist_ok=True)

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".avi")


@app.route("/version")
def version():
    return jsonify({"version": VERSION})


def get_videos():
    videos = []
    for ext in VIDEO_EXTENSIONS:
        for path in glob.glob(os.path.join(DOWNLOAD_DIR, f"*{ext}")):
            name = os.path.basename(path)
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
            videos.append({"filename": name, "size": size, "mtime": mtime, "path": path})
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return videos


def safe_filename(name):
    return re.sub(r"[^\w\-.]", "_", name)


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        cmd = [
            "yt-dlp", "--no-playlist", "--socket-timeout", "30",
            "--retries", "3", "--restrict-filenames",
            "-o", os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        ]
        if os.path.exists(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return jsonify({"status": "ok", "message": "Video downloaded!"})
        else:
            return jsonify({"error": result.stderr[-500:]}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/videos", methods=["GET"])
def list_videos():
    return jsonify(get_videos())


@app.route("/video/<path:filename>")
def stream_video(filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    file_size = os.path.getsize(filepath)
    range_header = request.headers.get("Range", None)
    if range_header:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1
        def generate():
            with open(filepath, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        }
        return Response(generate(), 206, headers=headers)
    return send_file(filepath)


@app.route("/delete", methods=["POST"])
def delete_video():
    data = request.get_json()
    filename = data.get("filename", "")
    folder = data.get("folder", "downloads")
    filepath = os.path.join(COMPILATIONS_DIR if folder == "compilations" else DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    os.remove(filepath)
    return jsonify({"status": "ok"})


@app.route("/move-to-library", methods=["POST"])
def move_to_library():
    data = request.get_json()
    filename = data.get("filename", "")
    src = os.path.join(COMPILATIONS_DIR, filename)
    if not os.path.exists(src):
        return jsonify({"error": "File not found"}), 404
    dst = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(dst):
        base, ext = os.path.splitext(filename)
        dst = os.path.join(DOWNLOAD_DIR, f"{base}_moved{ext}")
    shutil.move(src, dst)
    return jsonify({"status": "ok", "filename": os.path.basename(dst)})


@app.route("/video-duration/<path:filename>")
def video_duration(filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", filepath],
        capture_output=True, text=True
    )
    try:
        duration = float(result.stdout.strip())
        return jsonify({"duration": duration})
    except:
        return jsonify({"duration": 0})


@app.route("/rename", methods=["POST"])
def rename_existing():
    renamed = []
    for ext in VIDEO_EXTENSIONS:
        for path in glob.glob(os.path.join(DOWNLOAD_DIR, f"*{ext}")):
            name = os.path.basename(path)
            new_name = safe_filename(name)
            if new_name != name:
                new_path = os.path.join(DOWNLOAD_DIR, new_name)
                os.rename(path, new_path)
                renamed.append(f"{name} -> {new_name}")
    return jsonify({"status": "ok", "renamed": renamed})


@app.route("/merge", methods=["POST"])
def merge():
    data = request.get_json()
    clips = data.get("clips", [])
    output_name = data.get("output_name", "compilation").strip()
    if not clips:
        return jsonify({"error": "No clips provided"}), 400
    output_name = re.sub(r"[^\w\-]", "_", output_name)
    output_path = os.path.join(COMPILATIONS_DIR, f"{output_name}.mp4")
    temp_files = []
    concat_file = os.path.join(DOWNLOAD_DIR, "_concat.txt")
    try:
        for i, clip in enumerate(clips):
            filepath = os.path.join(DOWNLOAD_DIR, clip["filename"])
            if not os.path.exists(filepath):
                return jsonify({"error": f"File not found: {clip['filename']}"}), 400
            temp_path = os.path.join(DOWNLOAD_DIR, f"_temp_{i}.mp4")
            temp_files.append(temp_path)
            start = float(clip.get("start") or 0)
            end = clip.get("end")
            cmd = ["ffmpeg", "-y"]
            if start:
                cmd += ["-ss", str(start)]
            cmd += ["-i", filepath]
            if end:
                cmd += ["-t", str(float(end) - start)]
            cmd += ["-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", temp_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return jsonify({"error": f"v{VERSION} clip {i} failed: {result.stderr[-500:]}"}), 500
        with open(concat_file, "w") as f:
            for tp in temp_files:
                f.write(f"file '{tp}'\n")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return jsonify({"status": "ok", "output": os.path.basename(output_path)})
        else:
            return jsonify({"error": f"v{VERSION} concat failed: {result.stderr[-800:]}"}), 500
    except Exception as e:
        return jsonify({"error": f"v{VERSION} exception: {str(e)}"}), 500
    finally:
        for tp in temp_files:
            if os.path.exists(tp):
                os.remove(tp)
        if os.path.exists(concat_file):
            os.remove(concat_file)


@app.route("/trim", methods=["POST"])
def trim_video():
    data = request.get_json()
    filename = data.get("filename", "")
    start = float(data.get("start") or 0)
    end = data.get("end")
    mode = data.get("mode", "copy")
    src = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(src):
        return jsonify({"error": "File not found"}), 404
    base, ext = os.path.splitext(filename)
    if mode == "copy":
        out_name = f"{base}_trimmed{ext}"
        out_path = os.path.join(DOWNLOAD_DIR, out_name)
        counter = 1
        while os.path.exists(out_path):
            out_name = f"{base}_trimmed_{counter}{ext}"
            out_path = os.path.join(DOWNLOAD_DIR, out_name)
            counter += 1
    else:
        out_path = os.path.join(DOWNLOAD_DIR, f"_trimtmp_{filename}")
    cmd = ["ffmpeg", "-y"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", src]
    if end:
        cmd += ["-t", str(float(end) - start)]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", out_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return jsonify({"error": result.stderr[-500:]}), 500
        if mode == "overwrite":
            os.replace(out_path, src)
            out_name = filename
        return jsonify({"status": "ok", "filename": out_name})
    except Exception as e:
        if os.path.exists(out_path):
            os.remove(out_path)
        return jsonify({"error": str(e)}), 500


@app.route("/compilations/<path:filename>")
def stream_compilation(filename):
    filepath = os.path.join(COMPILATIONS_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(filepath)


@app.route("/compilations", methods=["GET"])
def list_compilations():
    videos = []
    for ext in VIDEO_EXTENSIONS:
        for path in glob.glob(os.path.join(COMPILATIONS_DIR, f"*{ext}")):
            videos.append({
                "filename": os.path.basename(path),
                "size": os.path.getsize(path),
                "mtime": os.path.getmtime(path)
            })
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return jsonify(videos)


@app.route("/browse", methods=["POST"])
def browse_profile():
    data = request.get_json()
    url = data.get("url", "").strip()
    offset = int(data.get("offset", 0))
    limit = int(data.get("limit", 10))
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        cmd = [
            "yt-dlp", "--flat-playlist", "--skip-download",
            "--print", "%(id)s\t%(title)s\t%(url)s\t%(duration)s",
            "--playlist-start", str(offset + 1),
            "--playlist-end", str(offset + limit),
            "--no-warnings",
        ]
        if os.path.exists(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0 and not result.stdout:
            return jsonify({"error": result.stderr[-400:]}), 500
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                videos.append({
                    "id": parts[0],
                    "title": parts[1] if parts[1] != "NA" else parts[0],
                    "url": parts[2],
                    "duration": parts[3] if len(parts) > 3 and parts[3] != "NA" else None
                })
        return jsonify({"videos": videos, "offset": offset, "count": len(videos)})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out — try again"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print(f"InstaGet server v{VERSION} — saving to: {DOWNLOAD_DIR}")
    app.run(host="0.0.0.0", port=5000, debug=False)
