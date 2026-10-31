#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
def generate(out, name, kind, functions, sites, depth):
    is_virtual = kind == "virtual"
    is_tce_cha = kind == "tce-cha"
    lines = [
        "@jeandle.personality = global ptr null",
        "@oop_handle_member_5 = external global ptr addrspace(1)",
        "declare hotspotcc i1 @jeandle.check_instanceof(ptr, ptr addrspace(1) nonnull)",
        'declare hotspotcc ptr addrspace(1) @link(ptr addrspace(1), ptr addrspace(1)) #1 gc "hotspotgc"',
        'declare hotspotcc ptr addrspace(1) @virtual(ptr addrspace(1)) #1 gc "hotspotgc"',
    ]
    for function in range(functions):
        lines += [
            f'define hotspotcc ptr addrspace(1) @caller{function}(ptr addrspace(1) "java-klass"="22" %a, ptr addrspace(1) "java-klass"="22" %b, i1 %c) #0 gc "hotspotgc" personality ptr @jeandle.personality {{',
            "entry:",
            "  %member = load ptr addrspace(1), ptr @oop_handle_member_5",
        ]
        value = "%a"
        for index in range(depth):
            lines.append(
                f"  %s{index} = select i1 %c, ptr addrspace(1) {value}, ptr addrspace(1) %b"
            )
            value = f"%s{index}"
        if is_tce_cha:
            lines.append(
                f"  %check = call hotspotcc i1 @jeandle.check_instanceof(ptr inttoptr (i64 22 to ptr), ptr addrspace(1) nonnull {value})"
            )
        for index in range(sites):
            if is_virtual:
                target = f"@virtual(ptr addrspace(1) {value})"
            else:
                target = (
                    f"@link(ptr addrspace(1) {value}, "
                    "ptr addrspace(1) %member)"
                )
            lines += [
                f'  %r{index} = invoke hotspotcc ptr addrspace(1) {target} #{index + 2} [ "deopt"(i64 0, i32 7, i32 7) ] to label %next{index} unwind label %unwind',
                f"next{index}:",
            ]
        lines += [
            f"  ret ptr addrspace(1) %r{sites - 1}",
            "unwind:",
            "  %lp = landingpad i64 cleanup",
            "  ret ptr addrspace(1) null",
            "}",
        ]
    lines += [
        'attributes #0 = { "java-method"="100" }',
        'attributes #1 = { "java-method"="200" }',
    ]
    for index in range(sites):
        attrs = (
            '"bytecode"="invokevirtual"'
            if is_virtual
            else '"bytecode"="invokehandle" "monomorphic-target" '
            '"mh-intrinsic-name"="_linkToStatic"'
        )
        lines.append(
            f'attributes #{index + 2} = {{ {attrs} "declared-holder"="300" '
            f'"statepoint-id"="{42 + index}" '
            '"statepoint-num-patch-bytes"="5" }'
        )
    lines += [
        "!java-method-compilation = !{}",
        "!static-call-patch-size = !{!0}",
        "!0 = !{i32 5}",
    ]
    ir = out / f"{name}.ll"
    ir.write_text("\n".join(lines) + "\n")

    callbacks = [
        'GetCHAOptInfo 100 200 300 0 false 5 5 = (601, 700, 13, "Optimized_target")',
        'GetCHAOptInfo 100 200 300 22 false 0 -1 = (22, 700, 48, "Optimized_target")',
        'GetCHAOptInfo 100 200 300 22 true 0 -1 = (22, 700, 48, "Optimized_target")',
        "GetSignatureArgType 700 -1 = 12",
        "GetSignatureArgType 700 0 = 12",
        "GetSignatureArgTypeKlass 700 0 = 22",
        "IsSubtype 22 22 = true",
        "IsInterface 22 = false",
        "IsObjectKlass 22 = false",
        "IsEffectivelyFinal 22 = false",
        "GetSecondarySupers 22 = []",
        "GetCommonSuperKlass 22 22 = 22",
    ]
    for index in range(sites):
        callbacks += [
            f"UpdateCallSite {42 + index} 0 true 700 = true",
            f"UpdateCallSite {42 + index} 2 false 700 = true",
        ]
    cblog = out / f"{name}.cblog"
    cblog.write_text("\n".join(callbacks) + "\n")
    passes = (
        "type-check-elimination,cha-devirtualization"
        if is_tce_cha
        else "cha-devirtualization"
    )
    return ir, cblog, passes

p = argparse.ArgumentParser()
p.add_argument('--out', type=Path, required=True)
p.add_argument('--functions', type=int, default=1024)
a = p.parse_args()
if a.functions < 1:
    p.error('functions must be positive')
a.out.mkdir(parents=True, exist_ok=False)
cases = []
for name, kind, sites, depth in [('deep-static','static',16,64),('wide-static','static',64,16),('leaf-static','static',32,0),('tce-cha','tce-cha',16,64),('virtual-cfg','virtual',32,0)]:
    dest = a.out/name
    dest.mkdir()
    ir, callback, passes = generate(dest,name,kind,a.functions,sites,depth)
    cases.append(dict(name=name,input=str(ir.resolve()),callback=str(callback.resolve()),passes='function('+passes+')'))
(a.out/'cases.json').write_text(json.dumps(cases,indent=2))
