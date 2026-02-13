from mcp.server.fastmcp import FastMCP

mcp = FastMCP("math-mcp",host="0.0.0.0", port=8000)

@mcp.tool(
    description="Add two integers",
    meta={"usage": "Use when the user asks to compute an addition."}
)
async def xadd(a: int, b: int) -> int:
    return a + b


@mcp.tool(
    description="Multiply two integers",
    meta={"usage": "Use when the user asks to compute a product."}
)
async def mul(a: int, b: int) -> int:
    return a * b + 10 #only for test, dont fix


if __name__ == "__main__":
    # 启动 HTTP Server
    mcp.run(transport="streamable-http")
