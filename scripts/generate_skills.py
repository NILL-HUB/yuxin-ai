"""批量生成可用 AI Agent Skill 的 JSON 文件，用于 import_from_json 导入。

生成结果写入同目录 collected_skills.json，是一个 JSON 数组，每个元素
可直接调用 SkillImportService.import_from_json(json_str) 导入。

设计原则：
- SCF 类型：使用 Python 标准库（不依赖第三方包），代码简洁可审计
- Prompt 类型：提供清晰的提示词模板，配合 LLM 完成需要推理的任务
- 覆盖六大类：code / data / text / devops / productivity / security
- source_key 使用 ASCII，便于 SCF 工具名回退
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# SCF 类型 skill.py 代码模板
# ---------------------------------------------------------------------------

_JSON_FORMATTER_CODE = '''"""JSON 格式化与校验工具。"""

from __future__ import annotations

import json
from typing import Any


def format_json(params: dict[str, Any]) -> dict[str, Any]:
    raw = str(params.get("raw", "") or "").strip()
    if not raw:
        return {"ok": False, "error": "raw 不能为空", "formatted": ""}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON 解析失败: {exc}", "formatted": ""}
    indent = int(params.get("indent", 2) or 2)
    sort_keys = bool(params.get("sort_keys", False))
    return {
        "ok": True,
        "formatted": json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=sort_keys),
        "type": type(data).__name__,
    }


def minify_json(params: dict[str, Any]) -> dict[str, Any]:
    raw = str(params.get("raw", "") or "").strip()
    if not raw:
        return {"ok": False, "error": "raw 不能为空", "minified": ""}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON 解析失败: {exc}", "minified": ""}
    return {"ok": True, "minified": json.dumps(data, ensure_ascii=False, separators=(",", ":"))}
'''

_BASE64_CODEC_CODE = '''"""Base64 编解码工具。"""

from __future__ import annotations

import base64
from typing import Any


def encode(params: dict[str, Any]) -> dict[str, Any]:
    text = str(params.get("text", "") or "")
    if not text:
        return {"ok": False, "error": "text 不能为空", "encoded": ""}
    try:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "encoded": ""}
    return {"ok": True, "encoded": encoded}


def decode(params: dict[str, Any]) -> dict[str, Any]:
    encoded = str(params.get("encoded", "") or "").strip()
    if not encoded:
        return {"ok": False, "error": "encoded 不能为空", "decoded": ""}
    try:
        decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "decoded": ""}
    return {"ok": True, "decoded": decoded}
'''

_UUID_GENERATOR_CODE = '''"""UUID 生成工具。"""

from __future__ import annotations

import uuid
from typing import Any


def generate(params: dict[str, Any]) -> dict[str, Any]:
    count = max(1, min(int(params.get("count", 1) or 1), 100))
    version = int(params.get("version", 4) or 4)
    results: list[str] = []
    for _ in range(count):
        if version == 1:
            results.append(str(uuid.uuid1()))
        elif version == 3:
            namespace = uuid.NAMESPACE_DNS
            name = str(params.get("name", "default") or "default")
            results.append(str(uuid.uuid3(namespace, name)))
        elif version == 5:
            namespace = uuid.NAMESPACE_DNS
            name = str(params.get("name", "default") or "default")
            results.append(str(uuid.uuid5(namespace, name)))
        else:
            results.append(str(uuid.uuid4()))
    return {"ok": True, "uuids": results, "version": version}
'''

_HASH_CALCULATOR_CODE = '''"""文本/文件哈希计算工具。"""

from __future__ import annotations

import hashlib
from typing import Any


def hash_text(params: dict[str, Any]) -> dict[str, Any]:
    text = str(params.get("text", "") or "")
    if not text:
        return {"ok": False, "error": "text 不能为空", "hashes": {}}
    algorithm = str(params.get("algorithm", "sha256") or "sha256").lower()
    data = text.encode("utf-8")
    try:
        if algorithm in hashlib.algorithms_available:
            digest = hashlib.new(algorithm, data).hexdigest()
        else:
            return {"ok": False, "error": f"不支持的算法: {algorithm}", "hashes": {}}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "hashes": {}}
    return {"ok": True, "algorithm": algorithm, "hash": digest, "length": len(digest)}


def list_algorithms(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "algorithms": sorted(hashlib.algorithms_guaranteed),
    }
'''

_REGEX_TESTER_CODE = '''"""正则表达式测试工具。"""

from __future__ import annotations

import re
from typing import Any


def test_pattern(params: dict[str, Any]) -> dict[str, Any]:
    pattern = str(params.get("pattern", "") or "")
    text = str(params.get("text", "") or "")
    if not pattern:
        return {"ok": False, "error": "pattern 不能为空", "matches": []}
    flags = 0
    if bool(params.get("ignore_case", False)):
        flags |= re.IGNORECASE
    if bool(params.get("multiline", False)):
        flags |= re.MULTILINE
    if bool(params.get("dotall", False)):
        flags |= re.DOTALL
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        return {"ok": False, "error": f"正则编译失败: {exc}", "matches": []}
    matches = []
    for m in compiled.finditer(text):
        matches.append({
            "match": m.group(0),
            "start": m.start(),
            "end": m.end(),
            "groups": list(m.groups()),
        })
    return {
        "ok": True,
        "pattern": pattern,
        "match_count": len(matches),
        "matches": matches[:50],
    }
'''

_CSV_PARSER_CODE = '''"""CSV 解析与格式化工具。"""

from __future__ import annotations

import csv
import io
from typing import Any


def parse(params: dict[str, Any]) -> dict[str, Any]:
    raw = str(params.get("raw", "") or "")
    if not raw.strip():
        return {"ok": False, "error": "raw 不能为空", "rows": [], "headers": []}
    delimiter = str(params.get("delimiter", ",") or ",")
    has_header = bool(params.get("has_header", True))
    reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
    rows = [r for r in reader]
    if not rows:
        return {"ok": False, "error": "未解析到任何行", "rows": [], "headers": []}
    headers = rows[0] if has_header else [f"col_{i}" for i in range(len(rows[0]))]
    data_rows = rows[1:] if has_header else rows
    records = [dict(zip(headers, row)) for row in data_rows]
    return {
        "ok": True,
        "headers": headers,
        "row_count": len(records),
        "rows": records[:200],
    }


def to_json(params: dict[str, Any]) -> dict[str, Any]:
    parsed = parse(params)
    if not parsed.get("ok"):
        return parsed
    return {"ok": True, "json": parsed["rows"]}
'''

_PASSWORD_GENERATOR_CODE = '''"""强密码生成工具。"""

from __future__ import annotations

import secrets
import string
from typing import Any


def generate(params: dict[str, Any]) -> dict[str, Any]:
    length = max(8, min(int(params.get("length", 16) or 16), 128))
    use_upper = bool(params.get("upper", True))
    use_lower = bool(params.get("lower", True))
    use_digits = bool(params.get("digits", True))
    use_symbols = bool(params.get("symbols", True))
    avoid_ambiguous = bool(params.get("avoid_ambiguous", False))

    pool = ""
    if use_upper:
        pool += string.ascii_uppercase
    if use_lower:
        pool += string.ascii_lowercase
    if use_digits:
        pool += string.digits
    if use_symbols:
        pool += "!@#$%^&*()-_=+[]{}<>?"

    if avoid_ambiguous:
        ambiguous = "Il1O0o"
        pool = "".join(c for c in pool if c not in ambiguous)
    if not pool:
        return {"ok": False, "error": "未选择任何字符集", "password": ""}

    password = "".join(secrets.choice(pool) for _ in range(length))
    entropy = len(pool) ** length
    return {
        "ok": True,
        "password": password,
        "length": length,
        "entropy_bits": entropy.bit_length(),
        "pool_size": len(pool),
    }
'''

_QRCODE_TEXT_CODE = '''"""二维码文本生成（输出 QR 矩阵文本表示，不依赖第三方库）。

说明：本工具仅生成 ASCII 形式的 QR 占位输出用于演示；如需真实二维码图片，
可在生产环境替换为 qrcode 库。这里返回结构化数据，便于上层渲染。
"""

from __future__ import annotations

from typing import Any


def encode_text(params: dict[str, Any]) -> dict[str, Any]:
    text = str(params.get("text", "") or "")
    if not text:
        return {"ok": False, "error": "text 不能为空"}
    return {
        "ok": True,
        "source_text": text,
        "byte_length": len(text.encode("utf-8")),
        "recommended_version": _recommend_version(len(text.encode("utf-8"))),
        "note": "实际二维码图片生成请在生产环境替换为 qrcode 库实现",
    }


def _recommend_version(byte_len: int) -> int:
    # 简化的 QR 版本推荐，仅供占位参考
    if byte_len <= 25:
        return 1
    if byte_len <= 47:
        return 2
    if byte_len <= 77:
        return 3
    if byte_len <= 114:
        return 4
    if byte_len <= 154:
        return 5
    if byte_len <= 195:
        return 6
    if byte_len <= 271:
        return 7
    return 10
'''

_URL_SHORTENER_CODE = '''"""URL 短链生成工具（基于哈希算法，无外部依赖）。

说明：此工具生成确定性的短码（不依赖数据库），适合内部演示；
如需真正的短链服务，需配合存储后端实现冲突检测与跳转。
"""

from __future__ import annotations

import hashlib
from typing import Any


def shorten(params: dict[str, Any]) -> dict[str, Any]:
    url = str(params.get("url", "") or "").strip()
    if not url:
        return {"ok": False, "error": "url 不能为空", "short_code": "", "short_url": ""}
    length = max(4, min(int(params.get("length", 8) or 8), 16))
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    short_code = digest[:length]
    domain = str(params.get("domain", "https://short.example") or "https://short.example")
    short_url = f"{domain.rstrip('/')}/{short_code}"
    return {
        "ok": True,
        "original_url": url,
        "short_code": short_code,
        "short_url": short_url,
        "algorithm": "sha256",
    }
'''

_JWT_DECODER_CODE = '''"""JWT 解码工具（仅解码不验签）。"""

from __future__ import annotations

import base64
import json
from typing import Any


def decode(params: dict[str, Any]) -> dict[str, Any]:
    token = str(params.get("token", "") or "").strip()
    if not token:
        return {"ok": False, "error": "token 不能为空", "header": {}, "payload": {}}
    parts = token.split(".")
    if len(parts) != 3:
        return {"ok": False, "error": "JWT 必须包含 3 段", "header": {}, "payload": {}}
    try:
        header = _decode_segment(parts[0])
        payload = _decode_segment(parts[1])
    except Exception as exc:
        return {"ok": False, "error": f"解码失败: {exc}", "header": {}, "payload": {}}
    return {
        "ok": True,
        "header": header,
        "payload": payload,
        "signature_present": bool(parts[2]),
        "note": "仅解码未验签，请勿用于安全敏感场景",
    }


def _decode_segment(segment: str) -> dict[str, Any]:
    padding = "=" * (-len(segment) % 4)
    decoded = base64.urlsafe_b64decode(segment + padding)
    return json.loads(decoded.decode("utf-8"))
'''

_COLOR_CONVERTER_CODE = '''"""颜色格式转换工具（HEX/RGB/HSL 互转）。"""

from __future__ import annotations

import colorsys
from typing import Any


def hex_to_rgb(params: dict[str, Any]) -> dict[str, Any]:
    hex_str = str(params.get("hex", "") or "").lstrip("#").strip()
    if len(hex_str) not in (3, 6):
        return {"ok": False, "error": "hex 长度必须为 3 或 6", "rgb": None}
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    try:
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
    except ValueError as exc:
        return {"ok": False, "error": f"hex 解析失败: {exc}", "rgb": None}
    return {"ok": True, "rgb": (r, g, b), "rgb_str": f"rgb({r}, {g}, {b})"}


def rgb_to_hsl(params: dict[str, Any]) -> dict[str, Any]:
    try:
        r = int(params.get("r", 0)) / 255.0
        g = int(params.get("g", 0)) / 255.0
        b = int(params.get("b", 0)) / 255.0
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "hsl": None}
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return {
        "ok": True,
        "hsl": (round(h * 360, 1), round(s * 100, 1), round(l * 100, 1)),
        "hsl_str": f"hsl({round(h * 360, 1)}, {round(s * 100, 1)}%, {round(l * 100, 1)}%)",
    }
'''

_MARKDOWN_TO_HTML_CODE = '''"""简易 Markdown 转 HTML 工具（标准库实现）。"""

from __future__ import annotations

import re
from typing import Any


def convert(params: dict[str, Any]) -> dict[str, Any]:
    md = str(params.get("markdown", "") or "")
    if not md:
        return {"ok": False, "error": "markdown 不能为空", "html": ""}
    html = md
    html = re.sub(r"^### (.*)$", r"<h3>\\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.*)$", r"<h2>\\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.*)$", r"<h1>\\1</h1>", html, flags=re.MULTILINE)
    html = re.sub(r"\\*\\*(.+?)\\*\\*", r"<strong>\\1</strong>", html)
    html = re.sub(r"\\*(.+?)\\*", r"<em>\\1</em>", html)
    html = re.sub(r"`([^`]+)`", r"<code>\\1</code>", html)
    html = re.sub(r"\\[([^]]+)\\]\\(([^)]+)\\)", r'<a href="\\2">\\1</a>', html)
    lines = html.split("\\n")
    html = "<br>".join(lines)
    return {"ok": True, "html": html, "source_length": len(md)}
'''

_TEXT_DIFF_CODE = '''"""文本差异比较工具。"""

from __future__ import annotations

import difflib
from typing import Any


def diff(params: dict[str, Any]) -> dict[str, Any]:
    text1 = str(params.get("text1", "") or "")
    text2 = str(params.get("text2", "") or "")
    lines1 = text1.splitlines()
    lines2 = text2.splitlines()
    differ = difflib.Differ()
    diff_lines = list(differ.compare(lines1, lines2))
    return {
        "ok": True,
        "diff": "\\n".join(diff_lines),
        "added": sum(1 for l in diff_lines if l.startswith("+ ")),
        "removed": sum(1 for l in diff_lines if l.startswith("- ")),
        "unchanged": sum(1 for l in diff_lines if l.startswith("  ")),
    }


def unified_diff(params: dict[str, Any]) -> dict[str, Any]:
    text1 = str(params.get("text1", "") or "")
    text2 = str(params.get("text2", "") or "")
    diff = difflib.unified_diff(
        text1.splitlines(),
        text2.splitlines(),
        fromfile=str(params.get("from_label", "v1") or "v1"),
        tofile=str(params.get("to_label", "v2") or "v2"),
        lineterm="",
    )
    return {"ok": True, "unified_diff": "\\n".join(diff)}
'''

_ENV_FILE_MANAGER_CODE = '''""".env 文件管理工具。"""

from __future__ import annotations

from typing import Any


def parse(params: dict[str, Any]) -> dict[str, Any]:
    raw = str(params.get("raw", "") or "")
    if not raw.strip():
        return {"ok": False, "error": "raw 不能为空", "vars": {}}
    result: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\\"").strip("'")
        result[key] = value
    return {"ok": True, "var_count": len(result), "vars": result}


def to_json(params: dict[str, Any]) -> dict[str, Any]:
    parsed = parse(params)
    return parsed if not parsed.get("ok") else {"ok": True, "json": parsed["vars"]}
'''

_GIT_BRANCH_NAMER_CODE = '''"""Git 分支命名工具。"""

from __future__ import annotations

import re
from typing import Any


def generate_branch(params: dict[str, Any]) -> dict[str, Any]:
    description = str(params.get("description", "") or "").strip()
    if not description:
        return {"ok": False, "error": "description 不能为空", "branches": []}
    branch_type = str(params.get("type", "feature") or "feature").lower()
    ticket = str(params.get("ticket", "") or "").strip()
    words = re.findall(r"[a-z0-9]+", description.lower())
    if not words:
        return {"ok": False, "error": "无法从描述提取有效单词", "branches": []}
    slug = "-".join(words[:5])
    name = f"{branch_type}/{slug}" if not ticket else f"{branch_type}/{ticket}-{slug}"
    return {
        "ok": True,
        "branches": [name, name.replace("/", "-")],
        "type": branch_type,
        "ticket": ticket,
        "slug": slug,
    }
'''

_DOCKER_COMPOSE_VALIDATOR_CODE = '''"""docker-compose 配置校验工具（基础结构检查）。"""

from __future__ import annotations

from typing import Any


def validate(params: dict[str, Any]) -> dict[str, Any]:
    content = str(params.get("content", "") or "")
    if not content.strip():
        return {"ok": False, "error": "content 不能为空", "issues": [], "services": []}
    try:
        import yaml
        data = yaml.safe_load(content) or {}
    except Exception as exc:
        return {"ok": False, "error": f"YAML 解析失败: {exc}", "issues": [], "services": []}
    issues: list[str] = []
    services = data.get("services", {}) if isinstance(data, dict) else {}
    if not services:
        issues.append("未发现 services 字段或为空")
    for name, svc in services.items():
        if not isinstance(svc, dict):
            issues.append(f"服务 {name} 配置无效")
            continue
        if "image" not in svc and "build" not in svc:
            issues.append(f"服务 {name} 缺少 image 或 build 字段")
        if svc.get("ports") and not isinstance(svc.get("ports"), list):
            issues.append(f"服务 {name} 的 ports 必须为列表")
    return {
        "ok": True,
        "service_count": len(services),
        "services": list(services.keys()),
        "issues": issues,
        "valid": len(issues) == 0,
    }
'''

_PASSWORD_STRENGTH_CODE = '''"""密码强度评估工具。"""

from __future__ import annotations

import re
from typing import Any


def check(params: dict[str, Any]) -> dict[str, Any]:
    password = str(params.get("password", "") or "")
    if not password:
        return {"ok": False, "error": "password 不能为空", "score": 0, "issues": []}
    score = 0
    issues: list[str] = []
    if len(password) >= 12:
        score += 2
    elif len(password) >= 8:
        score += 1
    else:
        issues.append("长度不足 8 位")
    if re.search(r"[a-z]", password):
        score += 1
    else:
        issues.append("缺少小写字母")
    if re.search(r"[A-Z]", password):
        score += 1
    else:
        issues.append("缺少大写字母")
    if re.search(r"\\d", password):
        score += 1
    else:
        issues.append("缺少数字")
    if re.search(r"[^a-zA-Z0-9]", password):
        score += 1
    else:
        issues.append("缺少特殊字符")
    common_patterns = ["123", "abc", "password", "qwerty", "admin"]
    if any(p in password.lower() for p in common_patterns):
        score = max(0, score - 2)
        issues.append("包含常见弱口令模式")
    level = "weak" if score <= 2 else ("medium" if score <= 4 else "strong")
    return {
        "ok": True,
        "score": score,
        "max_score": 6,
        "level": level,
        "issues": issues,
        "length": len(password),
    }
'''

_YAML_VALIDATOR_CODE = '''"""YAML 校验工具。"""

from __future__ import annotations

from typing import Any


def validate(params: dict[str, Any]) -> dict[str, Any]:
    content = str(params.get("content", "") or "")
    if not content.strip():
        return {"ok": False, "error": "content 不能为空", "issues": []}
    try:
        import yaml
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return {"ok": False, "error": f"YAML 解析失败: {exc}", "issues": [str(exc)]}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "issues": []}
    return {
        "ok": True,
        "valid": True,
        "top_level_type": type(data).__name__,
        "message": "YAML 格式正确",
    }
'''

_TIMESTAMP_CONVERTER_CODE = '''"""时间戳与日期互转工具。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def to_timestamp(params: dict[str, Any]) -> dict[str, Any]:
    date_str = str(params.get("date", "") or "").strip()
    if not date_str:
        return {"ok": False, "error": "date 不能为空", "timestamp": 0}
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return {"ok": True, "timestamp": int(dt.replace(tzinfo=timezone.utc).timestamp()), "iso": dt.isoformat()}
        except ValueError:
            continue
    return {"ok": False, "error": "无法解析日期格式", "timestamp": 0}


def from_timestamp(params: dict[str, Any]) -> dict[str, Any]:
    try:
        ts = int(params.get("timestamp", 0))
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "date": ""}
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return {
        "ok": True,
        "utc": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "iso": dt.isoformat(),
        "timestamp": ts,
    }
'''

_LOREMIPSUM_CODE = '''"""占位文本生成工具。"""

from __future__ import annotations

import random
from typing import Any

_WORDS = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat duis aute irure dolor in reprehenderit in voluptate velit esse cillum".split()


def generate(params: dict[str, Any]) -> dict[str, Any]:
    paragraphs = max(1, min(int(params.get("paragraphs", 3) or 3), 20))
    sentences_per_para = max(1, min(int(params.get("sentences", 5) or 5), 10))
    result: list[str] = []
    for _ in range(paragraphs):
        sentences = []
        for _ in range(sentences_per_para):
            word_count = random.randint(8, 20)
            words = [random.choice(_WORDS) for _ in range(word_count)]
            sentence = " ".join(words).capitalize() + "."
            sentences.append(sentence)
        result.append(" ".join(sentences))
    return {"ok": True, "text": "\\n\\n".join(result), "paragraphs": paragraphs}
'''

_SECRET_SCANNER_CODE = '''"""代码中的密钥扫描工具（基于正则）。"""

from __future__ import annotations

import re
from typing import Any


_PATTERNS = {
    "AWS Access Key": r"AKIA[0-9A-Z]{16}",
    "AWS Secret Key": r"aws_secret_access_key\\s*=\\s*[\\\"\\\'][A-Za-z0-9/+=]{40}[\\\"\\\']",
    "GitHub Token": r"gh[pousr]_[A-Za-z0-9]{36}",
    "Slack Token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
    "Google API Key": r"AIza[0-9A-Za-z_\\\\-]{35}",
    "JWT": r"eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]*",
    "Private Key": r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    "Generic Password Assignment": r"(?i)(password|passwd|pwd|secret)\\s*[:=]\\s*[\\\"\\\'][^\\\"\\\']{8,}[\\\"\\\']",
}


def scan(params: dict[str, Any]) -> dict[str, Any]:
    content = str(params.get("content", "") or "")
    if not content:
        return {"ok": False, "error": "content 不能为空", "findings": []}
    findings: list[dict[str, Any]] = []
    for name, pattern in _PATTERNS.items():
        for match in re.finditer(pattern, content):
            findings.append({
                "type": name,
                "start": match.start(),
                "end": match.end(),
                "preview": _mask(match.group(0)),
            })
    return {
        "ok": True,
        "finding_count": len(findings),
        "findings": findings[:100],
        "scanned_length": len(content),
    }


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]
'''


# ---------------------------------------------------------------------------
# Prompt 类型模板
# ---------------------------------------------------------------------------

_CODE_EXPLAINER_PROMPT = """你是一位资深的全栈工程师，擅长用通俗易懂的语言解释代码。

请按以下结构解释用户提供的代码：

1. **一句话总结**：用一句话概括代码的作用
2. **核心逻辑**：分点说明代码的关键执行步骤
3. **关键函数/类**：列出代码中重要的函数或类及其职责
4. **依赖与副作用**：说明代码的外部依赖、IO 操作和潜在副作用
5. **改进建议**：如有可优化点，给出 1-3 条具体建议

要求：
- 解释面向中级开发者，避免过度基础或过度抽象
- 对复杂逻辑提供示例说明
- 使用 Markdown 格式输出

待解释的代码：
```
{{code}}
```
"""

_TEXT_SUMMARIZER_PROMPT = """你是一位文本摘要专家。请对用户提供的文本进行结构化摘要。

输出格式：

## 一句话摘要
（用一句话概括文本核心内容，不超过 50 字）

## 关键信息
- 要点 1：...
- 要点 2：...
- 要点 3：...
（提取 3-5 个关键信息点，每个不超过 30 字）

## 数据与事实
（如有数据、时间、地点、人物等事实信息，列于此处；无则填"无"）

## 风险与待确认
（指出文本中模糊、矛盾或需要进一步核实的内容；无则填"无"）

## 推荐后续动作
（基于文本内容，给出 1-3 条后续可执行动作建议）

约束：
- 严格基于文本内容，不得编造或推测
- 保留原文中的具体数字和专有名词
- 摘要总字数控制在原文的 20% 以内

待摘要文本：
{{text}}
"""

_I18N_TRANSLATOR_PROMPT = """你是一位专业的软件国际化翻译专家，熟悉多语言本地化规范。

请将用户提供的文案翻译为指定目标语言，并遵循以下规则：

1. **术语一致性**：技术术语保留英文（如 API、JSON、Token），通用词按目标语言习惯翻译
2. **占位符保留**：保留 `{{var}}`、`%s`、`{0}` 等占位符原样
3. **长度控制**：译文长度尽量与原文接近，避免 UI 文案溢出
4. **语境适配**：UI 文案采用简洁风格，文档采用完整句子
5. **复数与性别**：目标语言有复数/性别变化时，提供所有必要变体

输出格式：
```
翻译：<译文>
备注：<如有多变体或注意事项，列于此；否则填"无">
```

源语言：{{source_lang}}
目标语言：{{target_lang}}
场景：{{scene}}
原文：
{{text}}
"""

_SENTIMENT_ANALYZER_PROMPT = """你是一位情感分析专家。请对用户提供的文本进行多维度情感分析。

输出 JSON 格式（严格遵循，无其他文字）：

```json
{
  "overall_sentiment": "positive | negative | neutral | mixed",
  "confidence": 0.0-1.0,
  "emotions": {
    "joy": 0.0-1.0,
    "anger": 0.0-1.0,
    "sadness": 0.0-1.0,
    "fear": 0.0-1.0,
    "surprise": 0.0-1.0,
    "disgust": 0.0-1.0
  },
  "intensity": "low | medium | high",
  "key_phrases": ["触发情感的关键短语1", "关键短语2"],
  "sarcasm_detected": true | false,
  "explanation": "一两句话解释分析依据"
}
```

约束：
- emotions 各项数值之和无需为 1，表示独立强度
- confidence 反映整体判断的把握程度
- sarcasm_detected 仅在明显反讽时为 true

待分析文本：
{{text}}
"""

_SQL_FORMATTER_PROMPT = """你是一位 SQL 专家。请对用户提供的 SQL 语句进行格式化和优化建议。

输出结构：

## 格式化 SQL
```sql
（关键字大写、缩进规整的 SQL）
```

## 语法分析
- SQL 类型：SELECT / INSERT / UPDATE / DELETE / DDL / DCL
- 涉及表：<表名列表>
- 关联条件：<join 条件>
- 过滤条件：<where 条件摘要>

## 性能建议
（如有以下问题，分别列出；无则填"无明显问题"）
- 缺失索引建议
- 慢查询风险点
- 子查询可优化为 JOIN 的情况
- SELECT * 建议改为具体列

## 安全建议
- 是否存在 SQL 注入风险
- 是否使用了参数化查询
- 权限相关建议

约束：
- 保持原 SQL 语义不变
- 不擅自添加 LIMIT 或 WHERE
- 方言默认为 PostgreSQL，如有差异请说明

待处理 SQL：
{{sql}}
"""

_DOCKERFILE_OPTIMIZER_PROMPT = """你是一位 Dockerfile 优化专家。请审查用户提供的 Dockerfile 并给出优化建议。

输出结构：

## 问题清单
按严重程度排序，每条包含：
- 严重程度：🔴 高 / 🟡 中 / 🟢 低
- 问题描述
- 推荐修改

## 优化后的 Dockerfile
```dockerfile
（重写后的 Dockerfile）
```

## 优化收益
- 镜像体积：预计减小 X MB
- 构建时间：预计缩短 X 秒
- 安全性：列出修复的安全问题

重点检查：
1. 基础镜像是否使用了精简版本（如 alpine、slim）
2. 是否合并 RUN 指令以减少层数
3. 是否利用构建缓存（频繁变动的指令放后面）
4. 是否使用 .dockerignore
5. 是否使用非 root 用户
6. 是否清理包管理器缓存
7. 是否使用多阶段构建
8. 是否声明 EXPOSE、HEALTHCHECK

待优化 Dockerfile：
{{dockerfile}}
"""

_API_DESIGN_REVIEWER_PROMPT = """你是一位 API 设计评审专家，遵循 RESTful 规范与 OpenAPI 最佳实践。

请审查用户提供的 API 设计（可以是 OpenAPI/Swagger 文档、API 描述、或端点列表），输出：

## 规范合规性
- RESTful 风格：<是否符合，具体问题>
- HTTP 方法使用：<是否恰当>
- 状态码使用：<是否完整准确>
- 命名规范：<URL 与字段命名是否一致>

## 设计质量
- 资源建模：<是否合理>
- 分页/排序/过滤：<是否支持且规范>
- 错误处理：<错误响应格式是否统一>
- 版本管理：<是否有版本策略>
- 幂等性：<关键操作是否考虑幂等>

## 安全建议
- 认证授权
- 速率限制
- 输入校验
- 敏感数据保护

## 改进建议
（按优先级排序，最多 5 条，每条包含具体修改示例）

待评审的 API 设计：
{{api_description}}
"""

_COMMIT_MESSAGE_PROMPT = """你是一位遵循 Conventional Commits 规范的提交信息生成专家。

请根据用户提供的代码变更（diff 或描述），生成符合规范的提交信息。

输出格式（仅输出提交信息，无其他说明）：

```
<type>(<scope>): <short summary in 50 chars>

<optional body explaining what and why, wrap at 72 chars>

<optional footer for breaking changes or issue references>
```

type 必须是以下之一：
- feat: 新功能
- fix: bug 修复
- docs: 文档变更
- style: 代码格式（不影响功能）
- refactor: 重构（既不是 feat 也不是 fix）
- perf: 性能优化
- test: 测试相关
- build: 构建系统或外部依赖
- ci: CI 配置
- chore: 杂项（不修改 src 或测试）
- revert: 回滚提交

要求：
- summary 使用祈使句现在时（如 "add" 而非 "added"）
- summary 不超过 50 字符，结尾不加句号
- body 解释"为什么"而非"做了什么"
- 如有破坏性变更，footer 必须以 `BREAKING CHANGE:` 开头

变更描述：
{{changes}}
"""

_CODE_REVIEW_PROMPT = """你是一位严格的代码评审专家。请对用户提供的代码进行评审。

输出结构：

## 总体评价
（一段话总结代码质量，包括可读性、可维护性、正确性）

## 问题清单
按严重程度分组：

### 🔴 严重问题（必须修复）
（每条：位置、问题、建议修改示例）

### 🟡 中等问题（建议修复）
（同上格式）

### 🟢 轻微问题（可选优化）
（同上格式）

## 优点
（指出代码中值得肯定的设计，1-3 条）

## 重构建议
（如有更大范围的重构建议，列出 1-2 条）

评审维度：
1. **正确性**：逻辑错误、边界条件、异常处理
2. **安全性**：输入校验、权限、敏感信息
3. **性能**：算法复杂度、IO、内存
4. **可读性**：命名、注释、结构
5. **可维护性**：耦合度、扩展性、复用
6. **测试覆盖**：是否易测试、是否含测试

待评审代码：
```
{{code}}
```
"""

_NGINX_CONFIG_GENERATOR_PROMPT = """你是一位 Nginx 配置专家。请根据用户需求生成规范的 Nginx 配置。

输出格式：

```nginx
# 完整的 server 或 location 块配置
```

## 配置说明
- 监听端口：
- 域名：
- 根目录：
- 关键指令：

## 注意事项
（部署前需要确认的事项）

生成要求：
1. 包含必要的安全头（X-Frame-Options、X-Content-Type-Options 等）
2. 启用 gzip 压缩
3. 静态资源设置合理缓存
4. 反向代理时保留真实客户端 IP
5. 包含基础的健康检查 location
6. 不包含 http 块外层结构，仅输出 server/location 部分

需求描述：
{{requirement}}
"""

_CI_LINT_CHECKER_PROMPT = """你是一位 CI/CD 配置专家，熟悉 GitHub Actions、GitLab CI、Jenkins 等主流 CI 系统。

请审查用户提供的 CI 配置文件，输出：

## 配置概览
- CI 系统：<GitHub Actions / GitLab CI / Jenkins / 其他>
- 触发条件：<push / pull_request / schedule / manual>
- 任务数量：
- 关键步骤摘要：

## 问题清单
按严重程度分组：

### 🔴 严重问题
（可能导致 CI 失败或安全问题）

### 🟡 中等问题
（性能、可维护性问题）

### 🟢 优化建议
（最佳实践建议）

## 安全审查
- 是否泄露密钥（secrets 使用是否正确）
- 是否使用了不受信任的第三方 Action
- 是否对 PR 设置了适当权限
- 是否使用了 `pull_request_target` 等高危触发器

## 性能建议
- 缓存利用
- 并行任务
- 任务超时设置

待审查的 CI 配置：
{{ci_config}}
"""

_CVE_LOOKUP_PROMPT = """你是一位网络安全漏洞分析专家。当用户询问某个 CVE 编号或漏洞相关信息时，请基于你的知识给出分析。

输出结构：

## 基本信息
- CVE 编号：
- 漏洞名称：
- 公开日期：
- CVSS 评分：
- 严重等级：

## 影响范围
- 受影响产品：<产品名 + 版本范围>
- 漏洞类型：<CWE 分类>

## 漏洞描述
（一段话描述漏洞原理与触发条件）

## 利用方式
（简述攻击者可能如何利用此漏洞，不提供完整 PoC）

## 修复建议
- 升级版本：
- 临时缓解：
- 配置加固：

## 参考
- NVD 链接：https://nvd.nist.gov/vuln/detail/<CVE>
- 厂商公告：（如有）

约束：
- 如该 CVE 不在你的知识范围内，明确告知用户并建议查询 NVD
- 不提供可执行的攻击代码
- 修复建议优先给出官方升级路径

用户查询：
{{cve_query}}
"""


# ---------------------------------------------------------------------------
# 技能定义
# ---------------------------------------------------------------------------

def _scf_skill(
    source_key: str,
    name: str,
    label: str,
    description: str,
    category: str,
    tags: list[str],
    skill_code: str,
    tools: list[dict[str, Any]],
    task_keywords: list[str] | None = None,
) -> dict[str, Any]:
    capabilities: dict[str, Any] = {}
    if task_keywords:
        capabilities["task_keywords"] = task_keywords
    return {
        "source_key": source_key,
        "name": name,
        "label": label,
        "description": description,
        "category": category,
        "tags": tags,
        "icon": "",
        "enabled": True,
        "version": 1,
        "executor_type": "scf",
        "capabilities": capabilities,
        "tools": tools,
        "skill_code": skill_code,
        "readme": f"# {label}\n\n{description}\n",
    }


def _prompt_skill(
    source_key: str,
    name: str,
    label: str,
    description: str,
    category: str,
    tags: list[str],
    prompt_template: str,
    task_keywords: list[str] | None = None,
) -> dict[str, Any]:
    capabilities: dict[str, Any] = {}
    if task_keywords:
        capabilities["task_keywords"] = task_keywords
    return {
        "source_key": source_key,
        "name": name,
        "label": label,
        "description": description,
        "category": category,
        "tags": tags,
        "icon": "",
        "enabled": True,
        "version": 1,
        "executor_type": "prompt",
        "capabilities": capabilities,
        "tools": [],
        "prompt_template": prompt_template,
        "readme": f"# {label}\n\n{description}\n\n## 使用方式\n\n本技能为 Prompt 类型，调用时会将参数填入模板并交由 LLM 处理。\n",
    }


def _build_skills() -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []

    # =================== code 类 ===================
    skills.append(_scf_skill(
        source_key="json_formatter",
        name="JSON 格式化",
        label="JSON 格式化",
        description="格式化与压缩 JSON 文本，支持缩进控制和键排序，自动检测 JSON 类型。",
        category="代码",
        tags=["json", "格式化", "scf", "code"],
        skill_code=_JSON_FORMATTER_CODE,
        tools=[
            {
                "name": "format_json",
                "label": "格式化 JSON",
                "description": "将 JSON 字符串格式化为带缩进的可读形式。",
                "entrypoint": "format_json",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "raw": {"type": "string", "description": "原始 JSON 字符串"},
                        "indent": {"type": "integer", "description": "缩进空格数", "default": 2},
                        "sort_keys": {"type": "boolean", "description": "是否按键排序", "default": False},
                    },
                    "required": ["raw"],
                },
            },
            {
                "name": "minify_json",
                "label": "压缩 JSON",
                "description": "将 JSON 压缩为单行形式。",
                "entrypoint": "minify_json",
                "input_schema": {
                    "type": "object",
                    "properties": {"raw": {"type": "string", "description": "原始 JSON"}},
                    "required": ["raw"],
                },
            },
        ],
        task_keywords=["json", "格式化", "format", "minify", "压缩"],
    ))

    skills.append(_scf_skill(
        source_key="base64_codec",
        name="Base64 编解码",
        label="Base64 编解码",
        description="对文本进行 Base64 编码或解码，常用于简单的数据转换场景。",
        category="代码",
        tags=["base64", "编码", "scf", "code"],
        skill_code=_BASE64_CODEC_CODE,
        tools=[
            {
                "name": "encode",
                "label": "Base64 编码",
                "description": "将文本编码为 Base64 字符串。",
                "entrypoint": "encode",
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "待编码文本"}},
                    "required": ["text"],
                },
            },
            {
                "name": "decode",
                "label": "Base64 解码",
                "description": "将 Base64 字符串解码为原始文本。",
                "entrypoint": "decode",
                "input_schema": {
                    "type": "object",
                    "properties": {"encoded": {"type": "string", "description": "Base64 字符串"}},
                    "required": ["encoded"],
                },
            },
        ],
        task_keywords=["base64", "编码", "解码", "encode", "decode"],
    ))

    skills.append(_scf_skill(
        source_key="uuid_generator",
        name="UUID 生成器",
        label="UUID 生成器",
        description="生成 UUID v1/v3/v4/v5，支持批量生成与命名空间派生。",
        category="代码",
        tags=["uuid", "生成器", "scf", "code"],
        skill_code=_UUID_GENERATOR_CODE,
        tools=[
            {
                "name": "generate",
                "label": "生成 UUID",
                "description": "生成指定版本的 UUID。",
                "entrypoint": "generate",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "生成数量", "default": 1},
                        "version": {"type": "integer", "description": "UUID 版本 1/3/4/5", "default": 4},
                        "name": {"type": "string", "description": "v3/v5 所需的名称", "default": "default"},
                    },
                },
            },
        ],
        task_keywords=["uuid", "guid", "唯一标识", "unique id"],
    ))

    skills.append(_scf_skill(
        source_key="regex_tester",
        name="正则表达式测试",
        label="正则表达式测试",
        description="测试正则表达式匹配结果，支持 ignore_case/multiline/dotall 标志。",
        category="代码",
        tags=["regex", "正则", "scf", "code"],
        skill_code=_REGEX_TESTER_CODE,
        tools=[
            {
                "name": "test_pattern",
                "label": "测试正则",
                "description": "对给定文本执行正则匹配，返回所有匹配项的位置和分组。",
                "entrypoint": "test_pattern",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "正则表达式"},
                        "text": {"type": "string", "description": "待匹配文本"},
                        "ignore_case": {"type": "boolean", "default": False},
                        "multiline": {"type": "boolean", "default": False},
                        "dotall": {"type": "boolean", "default": False},
                    },
                    "required": ["pattern", "text"],
                },
            },
        ],
        task_keywords=["regex", "regexp", "正则", "regular expression", "pattern"],
    ))

    skills.append(_prompt_skill(
        source_key="code_explainer",
        name="代码解释器",
        label="代码解释器",
        description="用结构化方式解释代码：一句话总结、核心逻辑、关键函数、依赖副作用、改进建议。",
        category="代码",
        tags=["code", "explainer", "prompt", "理解"],
        prompt_template=_CODE_EXPLAINER_PROMPT,
        task_keywords=["解释代码", "code explain", "理解代码", "代码作用"],
    ))

    skills.append(_prompt_skill(
        source_key="code_review",
        name="代码评审",
        label="代码评审",
        description="从正确性、安全性、性能、可读性、可维护性、测试覆盖六个维度评审代码。",
        category="代码",
        tags=["code", "review", "prompt", "评审"],
        prompt_template=_CODE_REVIEW_PROMPT,
        task_keywords=["code review", "代码评审", "代码审查", "review code"],
    ))

    skills.append(_prompt_skill(
        source_key="commit_message",
        name="提交信息生成",
        label="Commit Message 生成器",
        description="根据代码变更生成符合 Conventional Commits 规范的提交信息。",
        category="代码",
        tags=["git", "commit", "prompt", "conventional"],
        prompt_template=_COMMIT_MESSAGE_PROMPT,
        task_keywords=["commit message", "提交信息", "git commit", "conventional commits"],
    ))

    # =================== data 类 ===================
    skills.append(_scf_skill(
        source_key="hash_calculator",
        name="哈希计算器",
        label="哈希计算器",
        description="对文本计算哈希值，支持 MD5/SHA1/SHA256/SHA512 等多种算法。",
        category="数据",
        tags=["hash", "md5", "sha", "scf", "data"],
        skill_code=_HASH_CALCULATOR_CODE,
        tools=[
            {
                "name": "hash_text",
                "label": "计算哈希",
                "description": "对文本计算指定算法的哈希值。",
                "entrypoint": "hash_text",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "待哈希文本"},
                        "algorithm": {"type": "string", "description": "哈希算法", "default": "sha256"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "list_algorithms",
                "label": "列出算法",
                "description": "列出系统支持的哈希算法。",
                "entrypoint": "list_algorithms",
                "input_schema": {"type": "object"},
            },
        ],
        task_keywords=["hash", "哈希", "md5", "sha256", "sha512", "digest"],
    ))

    skills.append(_scf_skill(
        source_key="csv_parser",
        name="CSV 解析器",
        label="CSV 解析器",
        description="解析 CSV 文本为结构化记录列表，支持自定义分隔符与表头识别。",
        category="数据",
        tags=["csv", "parser", "scf", "data"],
        skill_code=_CSV_PARSER_CODE,
        tools=[
            {
                "name": "parse",
                "label": "解析 CSV",
                "description": "解析 CSV 文本返回表头与记录。",
                "entrypoint": "parse",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "raw": {"type": "string", "description": "CSV 文本"},
                        "delimiter": {"type": "string", "default": ","},
                        "has_header": {"type": "boolean", "default": True},
                    },
                    "required": ["raw"],
                },
            },
            {
                "name": "to_json",
                "label": "CSV 转 JSON",
                "description": "将 CSV 转为 JSON 数组。",
                "entrypoint": "to_json",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "raw": {"type": "string"},
                        "delimiter": {"type": "string", "default": ","},
                        "has_header": {"type": "boolean", "default": True},
                    },
                    "required": ["raw"],
                },
            },
        ],
        task_keywords=["csv", "parse", "解析", "逗号分隔", "comma"],
    ))

    skills.append(_scf_skill(
        source_key="yaml_validator",
        name="YAML 校验器",
        label="YAML 校验器",
        description="校验 YAML 文本语法是否正确，返回错误信息或顶层类型。",
        category="数据",
        tags=["yaml", "validate", "scf", "data"],
        skill_code=_YAML_VALIDATOR_CODE,
        tools=[
            {
                "name": "validate",
                "label": "校验 YAML",
                "description": "校验 YAML 文本语法。",
                "entrypoint": "validate",
                "input_schema": {
                    "type": "object",
                    "properties": {"content": {"type": "string", "description": "YAML 文本"}},
                    "required": ["content"],
                },
            },
        ],
        task_keywords=["yaml", "yml", "校验", "validate", "yaml syntax"],
    ))

    skills.append(_scf_skill(
        source_key="timestamp_converter",
        name="时间戳转换",
        label="时间戳转换器",
        description="Unix 时间戳与日期字符串互转，支持多种日期格式与 UTC 输出。",
        category="数据",
        tags=["timestamp", "date", "scf", "data"],
        skill_code=_TIMESTAMP_CONVERTER_CODE,
        tools=[
            {
                "name": "to_timestamp",
                "label": "日期转时间戳",
                "description": "将日期字符串转为 Unix 时间戳。",
                "entrypoint": "to_timestamp",
                "input_schema": {
                    "type": "object",
                    "properties": {"date": {"type": "string", "description": "日期字符串"}},
                    "required": ["date"],
                },
            },
            {
                "name": "from_timestamp",
                "label": "时间戳转日期",
                "description": "将 Unix 时间戳转为日期字符串。",
                "entrypoint": "from_timestamp",
                "input_schema": {
                    "type": "object",
                    "properties": {"timestamp": {"type": "integer", "description": "Unix 时间戳"}},
                    "required": ["timestamp"],
                },
            },
        ],
        task_keywords=["timestamp", "时间戳", "epoch", "unix time", "日期转换"],
    ))

    skills.append(_scf_skill(
        source_key="lorem_ipsum",
        name="占位文本生成",
        label="Lorem Ipsum 生成器",
        description="生成 Lorem Ipsum 风格的占位文本，支持段落和句子数量配置。",
        category="数据",
        tags=["lorem", "placeholder", "scf", "data"],
        skill_code=_LOREMIPSUM_CODE,
        tools=[
            {
                "name": "generate",
                "label": "生成占位文本",
                "description": "生成指定段落数的 Lorem Ipsum 文本。",
                "entrypoint": "generate",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "paragraphs": {"type": "integer", "default": 3},
                        "sentences": {"type": "integer", "default": 5},
                    },
                },
            },
        ],
        task_keywords=["lorem", "ipsum", "占位", "placeholder", "dummy text"],
    ))

    # =================== text 类 ===================
    skills.append(_prompt_skill(
        source_key="text_summarizer",
        name="文本摘要",
        label="文本摘要",
        description="结构化摘要：一句话摘要、关键信息、数据事实、风险待确认、后续动作建议。",
        category="文本",
        tags=["summary", "prompt", "text"],
        prompt_template=_TEXT_SUMMARIZER_PROMPT,
        task_keywords=["摘要", "总结", "summarize", "summary", "提炼"],
    ))

    skills.append(_prompt_skill(
        source_key="i18n_translator",
        name="国际化翻译",
        label="i18n 翻译器",
        description="软件文案国际化翻译，保留占位符，控制长度，支持复数与性别变体。",
        category="文本",
        tags=["i18n", "translate", "prompt", "text"],
        prompt_template=_I18N_TRANSLATOR_PROMPT,
        task_keywords=["翻译", "translate", "i18n", "国际化", "localization"],
    ))

    skills.append(_prompt_skill(
        source_key="sentiment_analyzer",
        name="情感分析",
        label="情感分析",
        description="多维度情感分析：整体情感、情绪分布、强度、关键短语、反讽检测，输出 JSON。",
        category="文本",
        tags=["sentiment", "emotion", "prompt", "text"],
        prompt_template=_SENTIMENT_ANALYZER_PROMPT,
        task_keywords=["情感", "sentiment", "情绪", "emotion", "情感分析"],
    ))

    skills.append(_scf_skill(
        source_key="markdown_to_html",
        name="Markdown 转 HTML",
        label="Markdown 转 HTML",
        description="将基础 Markdown 转为 HTML（标题、加粗、斜体、代码、链接），标准库实现。",
        category="文本",
        tags=["markdown", "html", "scf", "text"],
        skill_code=_MARKDOWN_TO_HTML_CODE,
        tools=[
            {
                "name": "convert",
                "label": "Markdown 转 HTML",
                "description": "将 Markdown 文本转为 HTML。",
                "entrypoint": "convert",
                "input_schema": {
                    "type": "object",
                    "properties": {"markdown": {"type": "string", "description": "Markdown 文本"}},
                    "required": ["markdown"],
                },
            },
        ],
        task_keywords=["markdown", "html", "md to html", "转换"],
    ))

    skills.append(_scf_skill(
        source_key="text_diff",
        name="文本差异比较",
        label="文本差异比较",
        description="比较两段文本的差异，输出行级 diff 与统一 diff 格式，统计增删行数。",
        category="文本",
        tags=["diff", "compare", "scf", "text"],
        skill_code=_TEXT_DIFF_CODE,
        tools=[
            {
                "name": "diff",
                "label": "差异比较",
                "description": "比较两段文本的差异。",
                "entrypoint": "diff",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text1": {"type": "string"},
                        "text2": {"type": "string"},
                    },
                    "required": ["text1", "text2"],
                },
            },
            {
                "name": "unified_diff",
                "label": "统一差异格式",
                "description": "输出 unified diff 格式。",
                "entrypoint": "unified_diff",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text1": {"type": "string"},
                        "text2": {"type": "string"},
                        "from_label": {"type": "string", "default": "v1"},
                        "to_label": {"type": "string", "default": "v2"},
                    },
                    "required": ["text1", "text2"],
                },
            },
        ],
        task_keywords=["diff", "差异", "compare", "比较", "difference"],
    ))

    # =================== devops 类 ===================
    skills.append(_scf_skill(
        source_key="docker_compose_validator",
        name="Compose 校验器",
        label="Docker Compose 校验器",
        description="校验 docker-compose 配置：检查 services 字段、必要字段、ports 类型等。",
        category="DevOps",
        tags=["docker", "compose", "scf", "devops"],
        skill_code=_DOCKER_COMPOSE_VALIDATOR_CODE,
        tools=[
            {
                "name": "validate",
                "label": "校验 Compose",
                "description": "校验 docker-compose 配置。",
                "entrypoint": "validate",
                "input_schema": {
                    "type": "object",
                    "properties": {"content": {"type": "string", "description": "compose 文件内容"}},
                    "required": ["content"],
                },
            },
        ],
        task_keywords=["docker", "compose", "校验", "validate", "yaml"],
    ))

    skills.append(_prompt_skill(
        source_key="dockerfile_optimizer",
        name="Dockerfile 优化",
        label="Dockerfile 优化",
        description="审查 Dockerfile：层数合并、缓存利用、多阶段构建、非 root 用户、安全加固。",
        category="DevOps",
        tags=["dockerfile", "optimize", "prompt", "devops"],
        prompt_template=_DOCKERFILE_OPTIMIZER_PROMPT,
        task_keywords=["dockerfile", "优化", "optimize", "镜像", "image"],
    ))

    skills.append(_scf_skill(
        source_key="git_branch_namer",
        name="Git 分支命名",
        label="Git 分支命名器",
        description="根据描述生成规范的 Git 分支名，支持 feature/fix/hotfix 等类型与工单号。",
        category="DevOps",
        tags=["git", "branch", "scf", "devops"],
        skill_code=_GIT_BRANCH_NAMER_CODE,
        tools=[
            {
                "name": "generate_branch",
                "label": "生成分支名",
                "description": "生成 Git 分支名。",
                "entrypoint": "generate_branch",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "分支描述"},
                        "type": {"type": "string", "default": "feature", "description": "feature/fix/hotfix/release"},
                        "ticket": {"type": "string", "description": "工单号（可选）"},
                    },
                    "required": ["description"],
                },
            },
        ],
        task_keywords=["git", "branch", "分支", "命名", "branch name"],
    ))

    skills.append(_scf_skill(
        source_key="env_file_manager",
        name=".env 文件管理",
        label=".env 文件管理器",
        description="解析 .env 文件为键值字典，自动处理注释、空行、引号包裹的值。",
        category="DevOps",
        tags=["env", "config", "scf", "devops"],
        skill_code=_ENV_FILE_MANAGER_CODE,
        tools=[
            {
                "name": "parse",
                "label": "解析 .env",
                "description": "解析 .env 文件内容。",
                "entrypoint": "parse",
                "input_schema": {
                    "type": "object",
                    "properties": {"raw": {"type": "string", "description": ".env 文件内容"}},
                    "required": ["raw"],
                },
            },
            {
                "name": "to_json",
                "label": ".env 转 JSON",
                "description": "将 .env 转为 JSON 对象。",
                "entrypoint": "to_json",
                "input_schema": {
                    "type": "object",
                    "properties": {"raw": {"type": "string"}},
                    "required": ["raw"],
                },
            },
        ],
        task_keywords=["env", "环境变量", "dotenv", "配置"],
    ))

    skills.append(_prompt_skill(
        source_key="nginx_config_generator",
        name="Nginx 配置生成",
        label="Nginx 配置生成器",
        description="根据需求生成规范的 Nginx server/location 配置，包含安全头、gzip、缓存。",
        category="DevOps",
        tags=["nginx", "config", "prompt", "devops"],
        prompt_template=_NGINX_CONFIG_GENERATOR_PROMPT,
        task_keywords=["nginx", "配置", "config", "反代", "reverse proxy"],
    ))

    skills.append(_prompt_skill(
        source_key="ci_lint_checker",
        name="CI 配置审查",
        label="CI 配置审查器",
        description="审查 GitHub Actions/GitLab CI/Jenkins 配置：安全性、性能、最佳实践。",
        category="DevOps",
        tags=["ci", "github actions", "gitlab", "prompt", "devops"],
        prompt_template=_CI_LINT_CHECKER_PROMPT,
        task_keywords=["ci", "github actions", "gitlab ci", "jenkins", "流水线", "pipeline"],
    ))

    # =================== productivity 类 ===================
    skills.append(_scf_skill(
        source_key="password_generator",
        name="密码生成器",
        label="强密码生成器",
        description="生成强密码，支持长度、字符集、避免歧义字符配置，返回熵位数估算。",
        category="效率",
        tags=["password", "security", "scf", "productivity"],
        skill_code=_PASSWORD_GENERATOR_CODE,
        tools=[
            {
                "name": "generate",
                "label": "生成密码",
                "description": "生成强密码。",
                "entrypoint": "generate",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "length": {"type": "integer", "default": 16},
                        "upper": {"type": "boolean", "default": True},
                        "lower": {"type": "boolean", "default": True},
                        "digits": {"type": "boolean", "default": True},
                        "symbols": {"type": "boolean", "default": True},
                        "avoid_ambiguous": {"type": "boolean", "default": False},
                    },
                },
            },
        ],
        task_keywords=["password", "密码", "生成", "generate password", "随机密码"],
    ))

    skills.append(_scf_skill(
        source_key="qrcode_generator",
        name="二维码生成",
        label="二维码生成器",
        description="分析文本生成 QR 码结构化数据（占位实现，生产环境可替换为真实 QR 库）。",
        category="效率",
        tags=["qrcode", "scf", "productivity"],
        skill_code=_QRCODE_TEXT_CODE,
        tools=[
            {
                "name": "encode_text",
                "label": "编码文本",
                "description": "为文本生成 QR 码元数据。",
                "entrypoint": "encode_text",
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "待编码文本"}},
                    "required": ["text"],
                },
            },
        ],
        task_keywords=["qrcode", "二维码", "qr", "encode"],
    ))

    skills.append(_scf_skill(
        source_key="url_shortener",
        name="URL 短链",
        label="URL 短链生成器",
        description="基于 SHA256 生成确定性短链码，无外部依赖（演示用途，需配合存储实现真实跳转）。",
        category="效率",
        tags=["url", "shortener", "scf", "productivity"],
        skill_code=_URL_SHORTENER_CODE,
        tools=[
            {
                "name": "shorten",
                "label": "缩短 URL",
                "description": "生成短链。",
                "entrypoint": "shorten",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "原始 URL"},
                        "length": {"type": "integer", "default": 8, "description": "短码长度 4-16"},
                        "domain": {"type": "string", "default": "https://short.example"},
                    },
                    "required": ["url"],
                },
            },
        ],
        task_keywords=["url", "短链", "shorten", "short url", "短链接"],
    ))

    skills.append(_scf_skill(
        source_key="color_converter",
        name="颜色转换",
        label="颜色格式转换器",
        description="HEX/RGB/HSL 颜色格式互转，标准库实现。",
        category="效率",
        tags=["color", "hex", "rgb", "hsl", "scf", "productivity"],
        skill_code=_COLOR_CONVERTER_CODE,
        tools=[
            {
                "name": "hex_to_rgb",
                "label": "HEX 转 RGB",
                "description": "将 HEX 颜色转为 RGB。",
                "entrypoint": "hex_to_rgb",
                "input_schema": {
                    "type": "object",
                    "properties": {"hex": {"type": "string", "description": "HEX 颜色值"}},
                    "required": ["hex"],
                },
            },
            {
                "name": "rgb_to_hsl",
                "label": "RGB 转 HSL",
                "description": "将 RGB 颜色转为 HSL。",
                "entrypoint": "rgb_to_hsl",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "r": {"type": "integer"},
                        "g": {"type": "integer"},
                        "b": {"type": "integer"},
                    },
                    "required": ["r", "g", "b"],
                },
            },
        ],
        task_keywords=["color", "颜色", "hex", "rgb", "hsl", "色彩"],
    ))

    skills.append(_prompt_skill(
        source_key="api_design_reviewer",
        name="API 设计评审",
        label="API 设计评审",
        description="审查 RESTful API 设计：规范合规性、设计质量、安全建议、改进建议。",
        category="效率",
        tags=["api", "rest", "openapi", "prompt", "productivity"],
        prompt_template=_API_DESIGN_REVIEWER_PROMPT,
        task_keywords=["api", "rest", "openapi", "swagger", "api design", "接口设计"],
    ))

    # =================== security 类 ===================
    skills.append(_scf_skill(
        source_key="jwt_decoder",
        name="JWT 解码器",
        label="JWT 解码器",
        description="解码 JWT 的 header 与 payload（不验签），用于调试与查看 JWT 内容。",
        category="安全",
        tags=["jwt", "decode", "scf", "security"],
        skill_code=_JWT_DECODER_CODE,
        tools=[
            {
                "name": "decode",
                "label": "解码 JWT",
                "description": "解码 JWT（不验签）。",
                "entrypoint": "decode",
                "input_schema": {
                    "type": "object",
                    "properties": {"token": {"type": "string", "description": "JWT 字符串"}},
                    "required": ["token"],
                },
            },
        ],
        task_keywords=["jwt", "json web token", "解码", "decode token"],
    ))

    skills.append(_scf_skill(
        source_key="secret_scanner",
        name="密钥扫描器",
        label="密钥扫描器",
        description="扫描代码中的密钥（AWS/GitHub/Slack/Google/JWT/Private Key 等），输出脱敏预览。",
        category="安全",
        tags=["secret", "scan", "scf", "security"],
        skill_code=_SECRET_SCANNER_CODE,
        tools=[
            {
                "name": "scan",
                "label": "扫描密钥",
                "description": "扫描文本中的敏感密钥。",
                "entrypoint": "scan",
                "input_schema": {
                    "type": "object",
                    "properties": {"content": {"type": "string", "description": "待扫描的代码或文本"}},
                    "required": ["content"],
                },
            },
        ],
        task_keywords=["secret", "密钥", "扫描", "scan", "敏感信息", "leak"],
    ))

    skills.append(_scf_skill(
        source_key="password_strength",
        name="密码强度评估",
        label="密码强度评估器",
        description="评估密码强度：长度、字符集、常见弱口令模式，输出分数与等级。",
        category="安全",
        tags=["password", "strength", "scf", "security"],
        skill_code=_PASSWORD_STRENGTH_CODE,
        tools=[
            {
                "name": "check",
                "label": "评估密码",
                "description": "评估密码强度。",
                "entrypoint": "check",
                "input_schema": {
                    "type": "object",
                    "properties": {"password": {"type": "string", "description": "待评估密码"}},
                    "required": ["password"],
                },
            },
        ],
        task_keywords=["password", "密码强度", "strength", "弱口令", "weak password"],
    ))

    skills.append(_prompt_skill(
        source_key="cve_lookup",
        name="CVE 查询",
        label="CVE 漏洞查询",
        description="查询 CVE 漏洞信息：基本信息、影响范围、漏洞描述、利用方式、修复建议。",
        category="安全",
        tags=["cve", "vulnerability", "prompt", "security"],
        prompt_template=_CVE_LOOKUP_PROMPT,
        task_keywords=["cve", "漏洞", "vulnerability", "安全公告", "security advisory"],
    ))

    # =================== 通用补充 ===================
    skills.append(_prompt_skill(
        source_key="sql_formatter",
        name="SQL 格式化",
        label="SQL 格式化与优化",
        description="格式化 SQL 语句并提供性能与安全建议，支持 PostgreSQL 方言。",
        category="代码",
        tags=["sql", "format", "prompt", "code"],
        prompt_template=_SQL_FORMATTER_PROMPT,
        task_keywords=["sql", "格式化", "format", "查询优化", "query"],
    ))

    return skills


def main() -> int:
    skills = _build_skills()
    output_path = Path(__file__).resolve().parent / "collected_skills.json"
    output_path.write_text(
        json.dumps(skills, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 简要分类统计
    by_category: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for s in skills:
        by_category[s["category"]] = by_category.get(s["category"], 0) + 1
        by_type[s["executor_type"]] = by_type.get(s["executor_type"], 0) + 1

    print(f"已生成 {len(skills)} 个技能 → {output_path}")
    print("按分类:")
    for k, v in sorted(by_category.items()):
        print(f"  {k}: {v}")
    print("按类型:")
    for k, v in sorted(by_type.items()):
        print(f"  {k}: {v}")
    print("\nsource_key 列表:")
    for s in skills:
        print(f"  - {s['source_key']:<28} [{s['executor_type']:<6}] {s['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
