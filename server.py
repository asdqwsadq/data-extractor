import sys
import json
import httpx
import csv
import io
from typing import Any

# ── Configuration ──────────────────────────────────────────────────────────────
MIMO_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
MIMO_KEY = "tp-c6w5jsmi9x28pgwhuq8gh9bshuib12qx7f3brwc80orthn51"
MIMO_MODEL = "mimo-v2.5-pro"

# ── Tool definition ────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "extract_structured",
        "description": "从HTML/JSON/CSV/自由文本中提取结构化数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "原始文本内容"},
                "format": {
                    "type": "string",
                    "enum": ["html", "json", "csv", "text"],
                    "description": "输入内容的格式",
                },
                "schema_description": {
                    "type": "string",
                    "description": "要提取的字段描述，如'提取所有产品名称、价格和评分'",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["json", "csv"],
                    "description": "输出格式",
                },
            },
            "required": ["text", "schema_description"],
        },
    }
]


# ── MiMo API call ──────────────────────────────────────────────────────────────
def call_mimo(
    text: str,
    fmt: str,
    schema_description: str,
    output_format: str = "json",
) -> str:
    """Call Xiaomi MiMo API to extract structured data."""
    fmt_label = {"html": "HTML", "json": "JSON", "csv": "CSV", "text": "自由文本"}
    label = fmt_label.get(fmt, "自由文本")

    system_prompt = (
        "你是一个结构化数据提取助手。根据用户的描述，从给定的内容中提取结构化数据并返回。"
        f"请以{output_format.upper()}格式返回结果。"
        "只返回结构化数据本身，不要添加额外的解释或说明。"
    )
    user_prompt = (
        f"输入格式：{label}\n"
        f"提取要求：{schema_description}\n\n"
        f"内容如下：\n{text[:100000]}"
    )

    payload = {
        "model": MIMO_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            f"{MIMO_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {MIMO_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ── Tool executor ──────────────────────────────────────────────────────────────
def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    if name != "extract_structured":
        return json.dumps({"error": f"Unknown tool: {name}"})

    text = arguments["text"]
    schema_description = arguments["schema_description"]
    fmt = arguments.get("format", "text")
    output_format = arguments.get("output_format", "json")

    try:
        result = call_mimo(text, fmt, schema_description, output_format)
        return result
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── MCP stdio protocol ─────────────────────────────────────────────────────────
def main():
    """MCP stdio transport main loop."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = msg.get("id")
        method = msg.get("method")

        # ── initialize ──────────────────────────────────────────────────────
        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "data-extractor",
                        "version": "1.0.0",
                    },
                },
            }

        # ── tools/list ──────────────────────────────────────────────────────
        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            }

        # ── tools/call ──────────────────────────────────────────────────────
        elif method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result_text = execute_tool(tool_name, arguments)

            # Try to parse as JSON for structured content
            try:
                parsed = json.loads(result_text)
                is_error = "error" in parsed
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": result_text,
                            }
                        ],
                        "isError": is_error,
                    },
                }
            except json.JSONDecodeError:
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": result_text,
                            }
                        ],
                    },
                }

        # ── ping / notifications ────────────────────────────────────────────
        elif method == "ping":
            response = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        else:
            # Notification (no id) — ignore
            if msg_id is None:
                continue
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
