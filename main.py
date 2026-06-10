import os
import json
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
    """递归扫描 JSON 对象，找出值是图片路径的 key"""
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
                # 如果 value 中有 key 的值是图片路径列表，展开为单独 item
                has_image_list = False
                for k, v in group_val.items():
                    if isinstance(v, list) and len(v) > 0 and is_image_path(v[0]):
                        has_image_list = True
                        break

                if has_image_list:
                    # 展开图片列表：每个图片路径一个 item
                    # 先收集非图片列表的字段作为共享属性
                    shared = {}
                    image_keys = {}
                    for k, v in group_val.items():
                        if isinstance(v, list) and len(v) > 0 and is_image_path(v[0]):
                            image_keys[k] = v
                        elif is_image_path(v):
                            shared[k] = v
                        elif not isinstance(v, list):
                            shared[k] = v

                    # 找到最长的图片列表作为主循环
                    main_key = max(image_keys.keys(), key=lambda k: len(image_keys[k])) if image_keys else None
                    if main_key:
                        main_list = image_keys[main_key]
                        for sub_idx, img_path in enumerate(main_list):
                            item_copy = dict(shared)
                            item_copy[main_key] = img_path
                            # 其他图片列表 key 取对应索引的值
                            for k, v in image_keys.items():
                                if k != main_key and sub_idx < len(v):
                                    item_copy[k] = v[sub_idx]
                            item_copy["_index"] = idx
                            item_copy["_group"] = group_key
                            item_copy["_sub_index"] = sub_idx
                            items.append(item_copy)
                            idx += 1
                    else:
                        item_copy = dict(group_val)
                        item_copy["_index"] = idx
                        item_copy["_group"] = group_key
                        items.append(item_copy)
                        idx += 1
                else:
                    # 普通字典套字典：value 本身是一个 item
                    item_copy = dict(group_val)
                    item_copy["_index"] = idx
                    item_copy["_group"] = group_key
                    items.append(item_copy)
                    idx += 1
            elif is_image_path(group_val):
                items.append({
                    "_index": idx,
                    "_group": group_key,
                    group_key: group_val
                })
                idx += 1
        return items
    return []


def resolve_image_path(image_path, json_dir):
    """
    解析 JSON 中的图片路径为绝对路径。
    支持绝对路径和相对路径（相对于 JSON 文件所在目录）。
    """
    if os.path.isabs(image_path):
        return image_path
    return os.path.normpath(os.path.join(json_dir, image_path))


# ============================================================
# 原有路由
# ============================================================

@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {}
    )


@app.get("/api/folders")
def list_folders(root_dir: str, path: str = ""):

    try:
        current_path = safe_join(root_dir, path)
    except:
        return {"folders": []}

    if not os.path.exists(current_path):
        return {"folders": []}

    folders = []

    try:
        for entry in os.scandir(current_path):
            if entry.is_dir():
                folders.append(entry.name)
    except:
        pass

    folders.sort()

    return {
        "folders": folders,
        "path": path
    }


@app.get("/api/images")
def list_images(root_dir: str, folder: str = "", page: int = 0):

    try:
        if folder:
            folder_path = safe_join(root_dir, folder)
        else:
            folder_path = root_dir
    except:
        return {"images": [], "has_more": False}

    if not os.path.exists(folder_path):
        return {"images": [], "has_more": False}

    files = []

    for entry in os.scandir(folder_path):

        if not entry.is_file():
            continue

        name = entry.name.lower()

        if name.endswith(("jpg", "jpeg", "png", "webp")):
            files.append(entry.name)

    files.sort()

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    page_files = files[start:end]

    urls = [
        f"/thumb?root_dir={root_dir}&folder={folder}&filename={f}"
        for f in page_files
    ]

    return {
        "images": urls,
        "has_more": end < len(files)
    }


@app.get("/thumb")
def get_thumb(root_dir: str, folder: str, filename: str):

    try:
        src_path = safe_join(root_dir, folder, filename)
    except:
        return {"error": "invalid path"}

    if not os.path.exists(src_path):
        return {"error": "file not found"}

    cache_folder = os.path.join(THUMB_DIR, folder)
    os.makedirs(cache_folder, exist_ok=True)

    thumb_path = os.path.join(cache_folder, filename + ".jpg")

    if not os.path.exists(thumb_path):

        try:

            img = Image.open(src_path)

            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            img.thumbnail(THUMB_SIZE)

            img.save(
                thumb_path,
                "JPEG",
                quality=85,
                optimize=True
            )

        except:
            return {"error": "image error"}

    return FileResponse(thumb_path)


@app.get("/image")
def get_image(root_dir: str, folder: str, filename: str):

    try:
        path = safe_join(root_dir, folder, filename)
    except:
        return {"error": "invalid path"}

    if not os.path.exists(path):
        return {"error": "file not found"}

    return FileResponse(path)


@app.get("/api/image_info")
def get_image_info(root_dir: str, folder: str, filename: str):

    try:
        path = safe_join(root_dir, folder, filename)
    except:
        return {"error": "invalid path"}

    if not os.path.exists(path):
        return {"error": "file not found"}

    try:
        img = Image.open(path)

        width, height = img.size
        channels = len(img.getbands())

        return {
            "filename": filename,
            "width": width,
            "height": height,
            "channels": channels
        }

    except:
        return {"error": "image error"}


@app.post("/api/delete_images")
def delete_images(root_dir: str, folder: str, request: DeleteRequest):
    """
    删除指定的图片文件
    """
    deleted = []
    errors = []

    for filename in request.filenames:
        try:
            path = safe_join(root_dir, folder, filename)
        except:
            errors.append({"filename": filename, "error": "invalid path"})
            continue

        if not os.path.exists(path):
            errors.append({"filename": filename, "error": "file not found"})
            continue

        try:
            os.remove(path)
            deleted.append(filename)

            # 同时删除对应的缩略图缓存
            thumb_dir = os.path.join(THUMB_DIR, folder)
            thumb_path = os.path.join(thumb_dir, filename + ".jpg")
            if os.path.exists(thumb_path):
                os.remove(thumb_path)

        except Exception as e:
            errors.append({"filename": filename, "error": str(e)})

    return {
        "deleted": deleted,
        "errors": errors,
        "total_deleted": len(deleted),
        "total_errors": len(errors)
    }


# ============================================================
# JSON 模式路由
# ============================================================

@app.get("/api/json_info")
def get_json_info(json_path: str):
    """
    读取 JSON 文件，返回其中所有值是图片路径的 key 列表。
    json_path: JSON 文件的绝对路径
    """
    if not os.path.isfile(json_path):
        return {"error": "file not found", "keys": []}

    if not json_path.lower().endswith(".json"):
        return {"error": "not a json file", "keys": []}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"error": f"json parse error: {str(e)}", "keys": []}

    keys = find_image_keys(data)
    total_items = len(data) if isinstance(data, list) else 1

    return {
        "keys": keys,
        "total_items": total_items,
        "json_dir": os.path.dirname(json_path)
    }


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
                selected_images[k] = [
                    f"/json_image?path={resolve_image_path(p, json_dir)}"
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
                other_image_urls[k] = f"/json_image?path={resolve_image_path(v, json_dir)}"
            elif isinstance(v, list):
                img_list = [x for x in v if is_image_path(x)]
                if img_list:
                    other_images[k] = img_list
                    other_image_urls[k] = [
                        f"/json_image?path={resolve_image_path(p, json_dir)}" for p in img_list
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

    # 生成缩略图缓存路径
    import hashlib
    cache_key = hashlib.md5(path.encode("utf-8")).hexdigest()
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

    return FileResponse(thumb_path)


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
