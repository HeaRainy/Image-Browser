import os
import json
import time
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
from PIL import Image


class DeleteRequest(BaseModel):
    filenames: List[str]

PAGE_SIZE = 30
THUMB_SIZE = (300, 300)

THUMB_DIR = ".thumb_cache"

app = FastAPI()

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

os.makedirs(THUMB_DIR, exist_ok=True)


def safe_join(base, *paths):
    path = os.path.abspath(os.path.join(base, *paths))
    base = os.path.abspath(base)
    if not path.startswith(base):
        raise Exception("invalid path")
    return path


# ============================================================
# JSON 模式辅助函数
# ============================================================

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def is_image_path(value):
    """判断一个值是否是图片路径（字符串且以图片扩展名结尾）"""
    if not isinstance(value, str):
        return False
    ext = os.path.splitext(value.lower())[1]
    return ext in IMAGE_EXTENSIONS


def _scan_image_keys(obj, keys, seen, depth=0):
    """递归扫描 JSON 对象，找出值是图片路径的key"""
    if depth > 10:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in seen:
                # 检查值本身是否是图片路径
                if is_image_path(v):
                    keys.append(k)
                    seen.add(k)
                # 检查值是列表时，列表元素是否是图片路径
                elif isinstance(v, list) and len(v) > 0:
                    if is_image_path(v[0]):
                        keys.append(k)
                        seen.add(k)
            # 递归扫描子结构
            if isinstance(v, (dict, list)):
                _scan_image_keys(v, keys, seen, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _scan_image_keys(item, keys, seen, depth + 1)


def find_image_keys(data):
    """
    递归扫描 JSON 数据，找出所有值是图片路径的 key。
    支持嵌套结构：列表套字典、字典套列表、字典套字典等。
    返回去重且保持顺序的 key 列表。
    """
    keys = []
    seen = set()
    _scan_image_keys(data, keys, seen)
    return keys


def flatten_json_items(data):
    """
    将各种 JSON 结构展平为统一的 item 列表。
    - 列表套字典：直接返回
    - 字典套列表/字典：每个顶层 key 的 value 作为一个 item，附带 _group 标记
    - 字典套字典且 value 含图片列表：将列表中每个图片路径作为单独 item
    返回 list[dict]，每个 dict 至少有 _index 和 _group 字段
    """
    if isinstance(data, list):
        items = []
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                item_copy = dict(item)
                item_copy["_index"] = idx
                item_copy["_group"] = None
                items.append(item_copy)
        return items
    elif isinstance(data, dict):
        items = []
        idx = 0
        for group_key, group_val in data.items():
            if isinstance(group_val, list):
                # 字典套列表：每个元素是一个 item
                for sub_idx, sub_item in enumerate(group_val):
                    if isinstance(sub_item, dict):
                        item_copy = dict(sub_item)
                        item_copy["_index"] = idx
                        item_copy["_group"] = group_key
                        item_copy["_sub_index"] = sub_idx
                        items.append(item_copy)
                        idx += 1
                    elif is_image_path(sub_item):
                        # 列表元素直接是图片路径
                        items.append({
                            "_index": idx,
                            "_group": group_key,
                            "_sub_index": sub_idx,
                            "images": [sub_item]
                        })
                        idx += 1
            elif isinstance(group_val, dict):
                # 字典套字典：检查是否需要展开图片列表
                # 如果 value 中有多图片字段，则每个图片作为单独 item
                image_keys = find_image_keys(group_val)
                if image_keys:
                    for img_key in image_keys:
                        img_val = group_val[img_key]
                        if isinstance(img_val, list):
                            for img_path in img_val:
                                if is_image_path(img_path):
                                    items.append({
                                        "_index": idx,
                                        "_group": group_key,
                                        "_sub_index": idx,
                                        img_key: img_path
                                    })
                                    idx += 1
                        elif is_image_path(img_val):
                            items.append({
                                "_index": idx,
                                "_group": group_key,
                                "_sub_index": idx,
                                img_key: img_val
                            })
                            idx += 1
                else:
                    # 无图片列表，整体作为一个 item
                    item_copy = dict(group_val)
                    item_copy["_index"] = idx
                    item_copy["_group"] = group_key
                    items.append(item_copy)
                    idx += 1
            elif is_image_path(group_val):
                # 字典值直接是图片路径
                items.append({
                    "_index": idx,
                    "_group": group_key,
                    "images": [group_val]
                })
                idx += 1
        return items
    return []


def resolve_image_path(path, json_dir):
    """解析 JSON 中的图片路径为绝对路径"""
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(json_dir, path))


def count_json_items(data):
    """统计 JSON 中的条目数量"""
    if isinstance(data, list):
        return len([item for item in data if isinstance(item, dict)])
    elif isinstance(data, dict):
        count = 0
        for group_val in data.values():
            if isinstance(group_val, list):
                count += len([item for item in group_val if isinstance(item, dict) or is_image_path(item)])
            elif isinstance(group_val, dict):
                image_keys = find_image_keys(group_val)
                if image_keys:
                    for img_key in image_keys:
                        img_val = group_val[img_key]
                        if isinstance(img_val, list):
                            count += len([v for v in img_val if is_image_path(v)])
                        elif is_image_path(img_val):
                            count += 1
                else:
                    count += 1
            elif is_image_path(group_val):
                count += 1
        return count
    return 0


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/clear_cache")
def clear_cache():
    """清理缩略图缓存"""
    import shutil
    if os.path.exists(THUMB_DIR):
        shutil.rmtree(THUMB_DIR)
        os.makedirs(THUMB_DIR, exist_ok=True)
    return {"status": "cache cleared"}


@app.get("/api/folders")
def get_folders(root_dir: str, path: str = ""):
    """获取根目录或指定路径下的所有子文件夹"""
    if path:
        # 如果有 path 参数，返回该路径下的文件夹
        target_path = safe_join(root_dir, path)
    else:
        target_path = root_dir
    
    if not os.path.isdir(target_path):
        return []

    folders = []
    for name in os.listdir(target_path):
        full_path = os.path.join(target_path, name)
        if os.path.isdir(full_path):
            folders.append(name)
    return sorted(folders)


@app.get("/api/images")
def get_images(root_dir: str, folder: str, page: int = 0):
    """分页获取图片列表"""
    folder_path = safe_join(root_dir, folder)
    if not os.path.isdir(folder_path):
        return {"images": [], "has_more": False}

    files = []
    for name in os.listdir(folder_path):
        ext = os.path.splitext(name.lower())[1]
        if ext in IMAGE_EXTENSIONS:
            files.append(name)

    files.sort()
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_files = files[start:end]

    # 添加时间戳防止缓存
    timestamp = int(time.time())
    urls = [
        f"/thumb?root_dir={root_dir}&folder={folder}&filename={f}&t={timestamp}"
        for f in page_files
    ]

    return {
        "images": list(zip(page_files, urls)),
        "has_more": end < len(files),
    }


@app.get("/thumb")
def get_thumb(root_dir: str, folder: str, filename: str):
    """生成并返回缩略图"""
    folder_path = safe_join(root_dir, folder)
    file_path = safe_join(folder_path, filename)

    if not os.path.isfile(file_path):
        return {"error": "file not found"}

    cache_folder = os.path.join(THUMB_DIR, folder)
    os.makedirs(cache_folder, exist_ok=True)

    thumb_path = os.path.join(cache_folder, filename + ".jpg")

    # 获取文件修改时间
    file_mtime = os.path.getmtime(file_path)

    # 如果缩略图不存在或文件已更新，重新生成
    if not os.path.exists(thumb_path) or os.path.getmtime(thumb_path) < file_mtime:
        try:
            img = Image.open(file_path)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.thumbnail(THUMB_SIZE)
            img.save(
                thumb_path,
                "JPEG",
                quality=85,
            )
        except:
            return {"error": "image error"}

    # 添加不缓存头
    response = FileResponse(thumb_path)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/image")
def get_image(root_dir: str, folder: str, filename: str):
    """返回原始图片"""
    folder_path = safe_join(root_dir, folder)
    file_path = safe_join(folder_path, filename)

    if not os.path.isfile(file_path):
        return {"error": "file not found"}

    return FileResponse(file_path)


@app.post("/api/delete")
def delete_images(req: DeleteRequest, root_dir: str, folder: str):
    """删除指定的图片文件"""
    folder_path = safe_join(root_dir, folder)

    deleted = []
    for filename in req.filenames:
        file_path = safe_join(folder_path, filename)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                deleted.append(filename)
                
                # 同时删除对应的缩略图缓存
                thumb_dir = os.path.join(THUMB_DIR, folder)
                thumb_path = os.path.join(thumb_dir, filename + ".jpg")
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
            except Exception as e:
                pass

    return {"deleted": deleted}


@app.get("/api/json_files")
def get_json_files(json_dir: str):
    """获取指定目录下的所有 JSON 文件"""
    if not os.path.isdir(json_dir):
        return []

    json_files = []
    for name in os.listdir(json_dir):
        if name.endswith(".json"):
            json_files.append(name)

    return sorted(json_files)


@app.get("/api/json_keys")
def get_json_keys(json_path: str):
    """获取 JSON 文件中所有包含图片路径的 key"""
    if not os.path.isfile(json_path):
        return []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return []

    keys = find_image_keys(data)
    return keys


@app.get("/api/json_info")
def get_json_info(json_path: str):
    """获取 JSON 文件的基本信息：keys 和总条目数"""
    if not os.path.isfile(json_path):
        return {"error": "file not found"}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {"error": "failed to parse JSON"}

    keys = find_image_keys(data)
    total_items = count_json_items(data)

    return {
        "keys": keys,
        "total_items": total_items
    }


@app.get("/api/json_structure")
def get_json_structure(json_path: str):
    """获取 JSON 文件的基本结构信息"""
    if not os.path.isfile(json_path):
        return {"error": "file not found"}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {"error": "failed to parse JSON"}

    # 判断基本类型
    is_list = isinstance(data, list)
    is_dict = isinstance(data, dict)

    # 获取顶层 keys（如果是字典）
    top_keys = []
    if is_dict:
        top_keys = list(data.keys())

    return {
        "is_list": is_list,
        "is_dict": is_dict,
        "top_keys": top_keys,
        "item_count": len(data) if is_list else len(top_keys)
    }


def get_json_dir(json_path: str):
    """获取 JSON 文件所在目录"""
    return os.path.dirname(json_path)


@app.get("/api/json_images")
def get_json_images(json_path: str, key: str, page: int = 0):
    """
    根据 JSON 文件和选定的 key（逗号分隔支持多选），分页返回每个 item 中各 key 对应的图片。
    返回 selected_images: {key: [urls]} 按选中 key 分组的图片 URL。
    """
    if not os.path.isfile(json_path):
        return {"items": [], "has_more": False}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {"items": [], "has_more": False}

    json_dir = os.path.dirname(json_path)
    items = flatten_json_items(data)

    # 支持多 key（逗号分隔）
    selected_keys = [k.strip() for k in key.split(",") if k.strip()]

    # 筛选包含至少一个选中 key 的 item
    filtered = []
    for item in items:
        # 检查是否有至少一个选中的 key
        has_any = False
        for k in selected_keys:
            if k in item:
                val = item[k]
                if isinstance(val, list) and any(is_image_path(v) for v in val):
                    has_any = True
                    break
                elif is_image_path(val):
                    has_any = True
                    break
        if not has_any:
            continue

        # 收集每个选中 key 的图片路径
        selected_images = {}
        for k in selected_keys:
            if k not in item:
                continue
            val = item[k]
            paths = []
            if isinstance(val, list):
                paths = [v for v in val if is_image_path(v)]
            elif is_image_path(val):
                paths = [val]
            if paths:
                # 添加时间戳防止缓存
                timestamp = int(time.time())
                selected_images[k] = [
                    f"/json_image?path={resolve_image_path(p, json_dir)}&t={timestamp}"
                    for p in paths
                ]

        # 收集未选中的其他图片 key（供参考）
        other_images = {}
        other_image_urls = {}
        for k, v in item.items():
            if k.startswith("_"):
                continue
            if k in selected_keys:
                continue
            if is_image_path(v):
                other_images[k] = v
                timestamp = int(time.time())
                other_image_urls[k] = f"/json_image?path={resolve_image_path(v, json_dir)}&t={timestamp}"
            elif isinstance(v, list):
                img_list = [x for x in v if is_image_path(x)]
                if img_list:
                    other_images[k] = img_list
                    timestamp = int(time.time())
                    other_image_urls[k] = [
                        f"/json_image?path={resolve_image_path(p, json_dir)}&t={timestamp}" for p in img_list
                    ]

        filtered.append({
            "index": item.get("_index", 0),
            "group": item.get("_group"),
            "sub_index": item.get("_sub_index"),
            "selected_images": selected_images,
            "other_images": other_images,
            "other_image_urls": other_image_urls
        })

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = filtered[start:end]

    return {
        "items": page_items,
        "has_more": end < len(filtered),
        "total_filtered": len(filtered)
    }


@app.get("/json_image")
def get_json_image(path: str):
    """
    根据 JSON 中引用的图片绝对路径，返回图片文件（缩略图或原图）。
    """
    if not os.path.isfile(path):
        return {"error": "file not found"}

    # 检查是否是图片
    ext = os.path.splitext(path.lower())[1]
    if ext not in IMAGE_EXTENSIONS:
        return {"error": "not an image"}

    # 获取文件修改时间用于缓存键
    file_mtime = os.path.getmtime(path)
    import hashlib
    cache_key = hashlib.md5(f"{path}{file_mtime}".encode("utf-8")).hexdigest()
    cache_folder = os.path.join(THUMB_DIR, "_json_images")
    os.makedirs(cache_folder, exist_ok=True)
    thumb_path = os.path.join(cache_folder, cache_key + ".jpg")

    if not os.path.exists(thumb_path):
        try:
            img = Image.open(path)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.thumbnail(THUMB_SIZE)
            img.save(thumb_path, "JPEG", quality=85, optimize=True)
        except:
            return FileResponse(path)

    # 添加不缓存头
    response = FileResponse(thumb_path)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/json_image_full")
def get_json_image_full(path: str):
    """
    返回 JSON 中引用的图片原图（用于查看器）。
    """
    if not os.path.isfile(path):
        return {"error": "file not found"}

    ext = os.path.splitext(path.lower())[1]
    if ext not in IMAGE_EXTENSIONS:
        return {"error": "not an image"}

    return FileResponse(path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
