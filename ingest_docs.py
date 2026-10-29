"""批量把一个文件夹里的 .txt / .md 文档灌进知识库（文档 RAG）。

放到项目根目录。用法（在项目根目录执行）：
    .venv\\Scripts\\python ingest_docs.py <文件夹路径>
例如：
    .venv\\Scripts\\python ingest_docs.py .\\docs_kb

会递归扫描该文件夹下所有 .txt/.md，切块、向量化后写入 pgvector。
"""

import pathlib
import sys

from app.services import rag


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python ingest_docs.py <文件夹路径>")
        sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    if not folder.is_dir():
        print(f"不是有效文件夹: {folder}")
        sys.exit(1)

    # 确保表和索引存在
    rag.ensure_table()

    files = [p for p in folder.rglob("*") if p.suffix.lower() in {".txt", ".md"}]
    if not files:
        print("没找到 .txt / .md 文件")
        return

    total = 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            n = rag.add_document(text, source=p.name)
            print(f"  + {p.name}: {n} 块")
            total += n
        except Exception as e:
            print(f"  ! {p.name} 失败: {e}")

    print(f"\n完成，共写入 {total} 块，来自 {len(files)} 个文件。")


if __name__ == "__main__":
    main()