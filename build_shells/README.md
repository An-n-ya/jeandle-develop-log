# 编译与测试 Jeandle

```bash
cd /home/zjj/jeandle/build_shells
./build.sh           # 默认 release
./build.sh release   # LLVM Release + JDK release
./build.sh debug     # LLVM Debug + JDK slowdebug
# 自定义并发数
JOBS=8 ./build.sh debug
```

脚本依次编译并安装 LLVM，再编译 JDK，默认 Release、X86、4 并发。
路径直接在 `build.sh` 开头修改，Boot JDK 使用本机的 JDK 21。

LLVM 使用 Ninja，构建目录为 `jeandle-llvm/build/build-ninja-release`
或 `jeandle-llvm/build/build-ninja-debug`，两种模式互不混用构建目录。
不能直接复用原来的 Makefiles 构建目录，因此首次运行需要完整编译，
以后重复执行即可增量编译。JDK 继续使用 Make，也支持增量编译。

Release 的 LLVM 安装到 `/home/zjj/jeandle-llvm-release`，JDK 产物在
`jeandle-jdk/build/linux-x86_64-server-release/images/jdk`。
Debug 的 LLVM 安装到 `/home/zjj/jeandle-llvm-debug`，JDK 产物在
`jeandle-jdk/build/linux-x86_64-server-slowdebug/images/jdk`。

## 测试

当前 `test.sh` 使用 release 构建，运行 `build.sh debug` 不会切换测试模式。

```bash
./test.sh                  # 默认：LLVM + JDK 的 JavaType 相关测试
./test.sh java-type llvm   # 只跑 LLVM 的 54 个 JavaType 相关用例
./test.sh java-type jdk    # 只跑 JDK 的 4 个相关 Java 测试文件
./test.sh all              # LLVM + JDK 的全部 Jeandle 专项测试
./test.sh all llvm         # 只跑 LLVM 的全部 Jeandle 专项测试
JOBS=8 ./test.sh           # 编译、lit 和 jtreg 均使用 8 并发
```

LLVM 使用构建目录中的 `llvm-lit`，测试文件取自源码树的
`llvm/test/Jeandle`。每次先增量编译所需工具，JavaType 范围为
`java-type-metadata-recovery`、`type-check-elimination` 和
`cha-devirtualization`，只需构建 `opt`、`FileCheck`。

JDK 使用 `make test`，JavaType 范围为 `compiler/jeandle` 下的
`typeMetadataRecovery` 和 `typeCheckElimination`。修改 LLVM 后，
请先执行 `build.sh` 更新 LLVM 安装及 JDK，再运行 JDK 测试；
`test.sh` 不负责安装 LLVM。只调试 LLVM pass 时可单独跑 LLVM 测试。

JDK 测试需要 jtreg。可使用 configure 已记录的 `JT_HOME`，也可以临时指定：

```bash
JT_HOME=/实际的/jtreg目录 ./test.sh
```

此目录必须包含 `lib/jtreg.jar`。当前已有 JDK 配置未找到 jtreg，
需要先准备该依赖。脚本会在开始编译、测试前检查所需构建配置及 jtreg。

lit 失败时输出具体命令与检查信息；JDK 结果位于
`jeandle-jdk/build/linux-x86_64-server-release/test-results/`，
工作文件位于同级 `test-support/`。任一步骤失败，脚本立即以非零状态退出。
`all` 指 Jeandle 专项测试，并非整个上游 LLVM/JDK 测试集；
架构不匹配或要求断言的部分用例可能被当前 Release/X86 配置跳过。
