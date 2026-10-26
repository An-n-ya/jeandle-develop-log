---
name: jeandle-code-access
description: Read-only access guide for Jeandle full LLVM source via SSH and the getJavaType selective-invalidation working changes via GitHub compare. Use when investigating Jeandle internals, reviewing getJavaType caching, or checking implementation context.
---

# Jeandle code access

## Choose the right source

- **Full Jeandle source / surrounding implementation context:** Use SSH to inspect the complete remote source tree at `annya@100.122.220.40:/home/annya/playground/jeandle/jeandle/jeandle-llvm/llvm`.
- **Current getJavaType cache optimization changes:** Use the GitHub comparison for `main...Atm2086:jeandle-llvm:feat/javatype-selective-invalidation`: https://github.com/jeandle/jeandle-llvm/compare/main...Atm2086:jeandle-llvm:feat/javatype-selective-invalidation
- These are **different views**: the SSH directory is a full checkout (whose current branch/commit must be verified), while the GitHub compare page shows differences between the specified base and working branch. Never assume the remote checkout matches the compare branch or that the compare includes the full source tree.

## SSH preflight

1. Before relying on SSH, check connectivity with a non-interactive, bounded command:

   ```sh
   ssh -o BatchMode=yes -o ConnectTimeout=5 annya@100.122.220.40 'printf "SSH reachable\n"'
   ```

2. If the connection fails or authentication is unavailable, report it. Do not assume access, request or expose secrets, or silently fall back to a different host.
3. Verify the expected checkout and its revision with read-only commands:

   ```sh
   ssh -o BatchMode=yes -o ConnectTimeout=5 annya@100.122.220.40 \
     'cd /home/annya/playground/jeandle/jeandle/jeandle-llvm/llvm && pwd && git rev-parse --show-toplevel && git rev-parse HEAD && git status --short --branch'
   ```

4. Inspect only what is needed, using read-only commands such as `rg`, `grep`, `find`, `sed`, `cat`, and `git show` / `git log`. Limit output when practical. For example:

   ```sh
   ssh -o BatchMode=yes -o ConnectTimeout=5 annya@100.122.220.40 \
     'cd /home/annya/playground/jeandle/jeandle/jeandle-llvm/llvm && rg -n "getJavaType" . | head -80'
   ```

## Review workflow

1. Start at the GitHub compare URL for changes introduced by the cache-optimization branch. Inspect the actual diff, including modified files, relevant tests, and revision identifiers.
2. Use the remote complete source checkout to trace callers, definitions, invariants, and behavior not visible in the diff. Record the checkout's revision when making conclusions.
3. Explicitly separate observations from **GitHub branch changes** and from the **remote full source checkout**. If the two revisions diverge, call out the discrepancy before attributing a behavior to the work branch.
4. Cite file paths and line numbers where possible, and distinguish verified findings from hypotheses. If either source is inaccessible, say what could not be checked.

## Safety and scope

- Remote SSH access is **read-only by default**. Do not modify remote files or repository state unless the user explicitly asks for that action. Avoid editors that might save, shell redirection to remote files, `sed -i`, `git checkout`, `git reset`, `git clean`, builds, scripts with side effects, or other mutation commands.
- Never run destructive or privileged commands. Do not install dependencies, push commits, alter git branches, or trigger remote changes without explicit authorization.
- Do not copy full source trees, private code, credentials, or large outputs outside the necessary review context without permission.
- GitHub comparison content may be public but must not be treated as proof of the remote checkout's current state.
