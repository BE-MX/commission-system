"""Configuration shared by AI management and image consumers."""

import re
from math import gcd


RESERVED_REQUEST_KEYS = {
    "model", "messages", "prompt", "system", "image", "images", "image_url",
    "mask", "stream", "n", "tools", "tool_choice",
}


def is_studio_preset(preset) -> bool:
    parameters = preset.parameters or {}
    if not isinstance(parameters, dict):
        return False
    studio = parameters.get("studio", {})
    if not isinstance(studio, dict):
        return False
    enabled = studio.get("enabled")
    if enabled is not None:
        return enabled is True
    name = preset.preset_name or ""
    return name == "design_image_generation" or name.startswith("design_image_generation_")


def is_image_preset(preset) -> bool:
    parameters = preset.parameters or {}
    mode = parameters.get("test_mode")
    if mode:
        return mode == "image"
    return (is_studio_preset(preset) or "api_style" in parameters
            or preset.preset_name in {"expo_wig_composite", "customer_image_generation", "swatch_image_generation"})


def image_api_style(parameters) -> str:
    return str((parameters or {}).get("api_style") or "images").strip().lower()


def validate_parameters(parameters) -> None:
    if parameters is None:
        return
    if not isinstance(parameters, dict):
        raise ValueError("调用参数必须是 JSON 对象")
    if "studio" in parameters:
        studio = parameters["studio"]
        if not isinstance(studio, dict):
            raise ValueError("studio 必须是 JSON 对象")
        if "enabled" in studio and type(studio["enabled"]) is not bool:
            raise ValueError("studio.enabled 必须是布尔值")
        if "label" in studio and (not isinstance(studio["label"], str) or len(studio["label"]) > 128):
            raise ValueError("生图显示名称最长 128 字")
        for key in ("sizes", "qualities"):
            if key not in studio:
                continue
            values = studio[key]
            if (not isinstance(values, list) or not 1 <= len(values) <= 20
                    or any(not isinstance(value, str) or not value.strip() or len(value) > 64 for value in values)
                    or len(set(values)) != len(values)):
                raise ValueError(f"studio.{key} 必须是 1 到 20 个不重复的非空字符串")
    if "api_style" in parameters and (not isinstance(parameters["api_style"], str) or image_api_style(parameters) not in ("images", "chat")):
        raise ValueError("生图接口形式必须是 images 或 chat")
    if "max_reference_images" in parameters:
        limit = parameters["max_reference_images"]
        if type(limit) is not int or not 0 <= limit <= 5:
            raise ValueError("max_reference_images 必须是 0 到 5 的整数")
    if "size_parameter" in parameters and parameters["size_parameter"] not in ("size", "aspect_ratio"):
        raise ValueError("size_parameter 必须是 size 或 aspect_ratio")
    if "download_hosts" in parameters:
        hosts = parameters["download_hosts"]
        if not isinstance(hosts, list) or any(
            not isinstance(host, str) or not host.strip() or any(c in host for c in "/:@*?# ")
            for host in hosts
        ):
            raise ValueError("download_hosts 必须是下载域名数组（不含协议、路径或通配符）")
    from app.ai.provider_config import validate_transport_options
    from app.ai.workflow_config import validate_workflow_options
    if "workflow" in parameters:
        validate_workflow_options(parameters["workflow"])
    if "transport" in parameters:
        validate_transport_options(parameters["transport"])
    if "test_mode" in parameters and parameters["test_mode"] not in ("text", "image"):
        raise ValueError("测试模式须为 text 或 image")
    extras = parameters.get("request_parameters", {})
    if not isinstance(extras, dict):
        raise ValueError("request_parameters 必须是 JSON 对象")
    forbidden = RESERVED_REQUEST_KEYS.intersection(extras)
    if forbidden:
        raise ValueError("扩展参数不能覆盖业务请求字段：" + ", ".join(sorted(forbidden)))


def image_request_parameters(parameters) -> dict:
    validate_parameters(parameters)
    return dict((parameters or {}).get("request_parameters", {}))


INTERNAL_PARAMETER_KEYS = {
    "studio", "api_style", "download_hosts", "rate_card", "max_reference_images",
    "size_parameter", "request_parameters", "transport", "test_mode", "workflow",
}


def text_request_parameters(parameters) -> dict:
    """Keep management metadata local and preserve caller-owned model/messages."""
    validate_parameters(parameters)
    result = {key: value for key, value in (parameters or {}).items()
              if key not in INTERNAL_PARAMETER_KEYS | RESERVED_REQUEST_KEYS}
    result.update((parameters or {}).get("request_parameters", {}))
    return result


def studio_generation_options(parameters) -> dict:
    parameters = parameters or {}
    studio = parameters.get("studio") or {}
    sizes = studio.get("sizes", ["1024x1024", "1024x1536", "1536x1024"])
    qualities = studio.get("qualities", ["low", "medium", "high"])
    size = parameters.get("size", "1024x1024")
    quality = parameters.get("quality", "medium")
    return {"sizes": sizes, "qualities": qualities,
            "default_size": size if size in sizes else sizes[0],
            "default_quality": quality if quality in qualities else qualities[0]}


def image_size_parameter(parameters, model: str) -> str:
    return (parameters or {}).get("size_parameter", "size")


def image_aspect_ratio(size: str) -> str:
    match = re.fullmatch(r"([1-9]\d*)[x:]([1-9]\d*)", str(size))
    if match is None:
        raise ValueError("宽高比映射的尺寸须使用 WIDTHxHEIGHT 或 WIDTH:HEIGHT")
    width, height = map(int, match.groups())
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def validate_image_parameters(parameters, model: str) -> None:
    validate_parameters(parameters)
    if image_size_parameter(parameters, model) == "aspect_ratio":
        options = studio_generation_options(parameters)
        for size in options["sizes"]:
            image_aspect_ratio(size)
        if (parameters or {}).get("size"):
            image_aspect_ratio(parameters["size"])
