from mcp.server.fastmcp import FastMCP

mcp = FastMCP("math-mcp")


@mcp.tool(
    description="Add two integers",
    meta={"usage": "Use when the user asks to compute an addition."},
)
def add(a: int, b: int) -> int:
    return a + b


@mcp.tool(
    description="Multiply two integers",
    meta={"usage": "Use when the user asks to compute a product."},
)
def mul(a: int, b: int) -> int:
    return a * b


if __name__ == "__main__":
    mcp.run()
