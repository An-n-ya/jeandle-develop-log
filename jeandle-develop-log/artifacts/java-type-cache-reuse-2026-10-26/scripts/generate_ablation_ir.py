#!/usr/bin/env python3
"""Generate repeated TCE -> RecoverTypeInfo ablation modules."""

import argparse
from pathlib import Path


DECLARATIONS = """\
declare i1 @jeandle.check_instanceof(ptr, ptr addrspace(1) nonnull)

"""


def emit_function(index: int, folded: bool) -> str:
    name = f"bench_{index}"
    if folded:
        receiver = (
            'ptr addrspace(1) nonnull "java-klass"="9" '
            '"java-klass-exact" %obj'
        )
    else:
        receiver = "ptr addrspace(1) nonnull %obj"
    return f"""\
define void @{name}({receiver}) #0 gc "hotspotgc" {{
entry:
  %c0 = call i1 @jeandle.check_instanceof(ptr inttoptr (i64 9 to ptr), ptr addrspace(1) nonnull %obj)
  %c1 = call i1 @jeandle.check_instanceof(ptr inttoptr (i64 9 to ptr), ptr addrspace(1) nonnull %obj)
  %p0 = getelementptr i8, ptr addrspace(1) %obj, i64 16
  %l0 = load ptr addrspace(1), ptr addrspace(1) %p0, align 8
  %p1 = getelementptr i8, ptr addrspace(1) %obj, i64 24
  %l1 = load ptr addrspace(1), ptr addrspace(1) %p1, align 8
  ret void
}}

"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--folded", action="store_true")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    parts = [DECLARATIONS]
    parts.extend(emit_function(i, args.folded) for i in range(args.count))
    parts.append('attributes #0 = { "java-method"="0" }\n')
    parts.append("!java-method-compilation = !{}\n")
    args.output.write_text("".join(parts), encoding="ascii")


if __name__ == "__main__":
    main()
