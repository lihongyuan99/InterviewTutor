import json
import os
from typing import Any, Dict, Union

def ensure_directory(path: str):
    """Ensure the directory exists for the given file path."""
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

def save_text(content: str, file_path: str, mode: str = "w", encoding: str = "utf-8") -> str:
    """
    Save text content to a file.
    Automatically creates parent directories if they don't exist.
    Returns the absolute path of the saved file.
    """
    abs_path = os.path.abspath(file_path)
    ensure_directory(abs_path)
    
    with open(abs_path, mode, encoding=encoding) as f:
        f.write(content)
        
    return abs_path

def load_text(file_path: str, encoding: str = "utf-8") -> str:
    """Load text content from a file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    with open(file_path, "r", encoding=encoding) as f:
        return f.read()

def save_json(data: Union[Dict, list], file_path: str, indent: int = 2, encoding: str = "utf-8") -> str:
    """
    Save data structure as JSON file.
    Automatically handles directory creation.

    采用原子写：先写临时文件，再 ``os.replace`` 原子替换目标文件，
    避免写入中途崩溃或并发写入导致目标文件损坏/清空。
    """
    abs_path = os.path.abspath(file_path)
    ensure_directory(abs_path)

    tmp_path = f"{abs_path}.tmp"
    with open(tmp_path, "w", encoding=encoding) as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, default=str)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, abs_path)

    return abs_path

def load_json(file_path: str, encoding: str = "utf-8") -> Any:
    """Load and parse a JSON file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    with open(file_path, "r", encoding=encoding) as f:
        return json.load(f)
