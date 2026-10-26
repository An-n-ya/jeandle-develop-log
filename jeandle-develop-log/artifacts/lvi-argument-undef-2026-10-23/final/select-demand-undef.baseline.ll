; ModuleID = '/home/annya/playground/jeandle/jeandle/jeandle-llvm/llvm/test/Transforms/CorrelatedValuePropagation/select-demand-undef.ll'
source_filename = "/home/annya/playground/jeandle/jeandle/jeandle-llvm/llvm/test/Transforms/CorrelatedValuePropagation/select-demand-undef.ll"

define i1 @plain_condition(i1 %c) {
  %s = select i1 %c, i32 5, i32 7
  ret i1 true
}

define i1 @pointer_condition(i1 %c, ptr %p) {
  %s = select i1 %c, ptr %p, ptr null
  %r = icmp eq ptr %s, null
  ret i1 %r
}

define i1 @noundef_refinement(i32 noundef %x) {
  %c = icmp slt i32 %x, 0
  %s = select i1 %c, i32 %x, i32 0
  ret i1 true
}

define i1 @may_undef_refinement(i32 %x) {
  %c = icmp slt i32 %x, 0
  %s = select i1 %c, i32 %x, i32 0
  ret i1 true
}

define i1 @freeze_refinement(i32 %x) {
  %f = freeze i32 %x
  %c = icmp slt i32 %f, 0
  %s = select i1 %c, i32 %f, i32 0
  ret i1 true
}

define i1 @undef_condition() {
  %s = select i1 undef, i32 5, i32 7
  ret i1 true
}

define i1 @poison_condition() {
  %s = select i1 poison, i32 5, i32 7
  ret i1 true
}

define i1 @irrelevant_comparison(i32 noundef %x, i32 %y) {
  %c = icmp slt i32 %x, 0
  %s = select i1 %c, i32 %y, i32 0
  %r = icmp sle i32 %s, 0
  ret i1 %r
}

define i1 @and_condition(i32 noundef %x) {
  %lo = icmp sgt i32 %x, 0
  %hi = icmp slt i32 %x, 10
  %c = and i1 %lo, %hi
  %s = select i1 %c, i32 %x, i32 1
  ret i1 true
}

define i1 @or_condition(i32 noundef %x) {
  %lo = icmp slt i32 %x, 0
  %hi = icmp sgt i32 %x, 10
  %c = or i1 %lo, %hi
  %s = select i1 %c, i32 %x, i32 0
  ret i1 true
}

; Function Attrs: nocallback nofree nosync nounwind willreturn memory(inaccessiblemem: write)
declare void @llvm.assume(i1 noundef) #0

define i1 @assumed_condition(i32 %x) {
  %c = icmp slt i32 %x, 0
  call void @llvm.assume(i1 %c)
  ret i1 true
}

define i32 @loop_condition(i1 %c, i1 %exit, i32 %x) {
entry:
  br label %loop

loop:                                             ; preds = %loop, %entry
  %p = phi i32 [ %x, %entry ], [ %s, %loop ]
  %s = select i1 %c, i32 %p, i32 5
  br i1 %exit, label %done, label %loop

done:                                             ; preds = %loop
  ret i32 %s
}

define i1 @noundef_plain_condition(i1 noundef %c) {
  %s = select i1 %c, i32 5, i32 7
  ret i1 true
}

define range(i64 -2147483648, 2147483648) i64 @shared_boolean_condition(i32 %x) {
  %lo = icmp sgt i32 %x, 1
  %hi = icmp slt i32 %x, 100
  %c = and i1 %lo, %hi
  %d0 = and i1 %c, %c
  %d1 = and i1 %d0, %d0
  %d2 = and i1 %d1, %d1
  %d3 = and i1 %d2, %d2
  %s = select i1 %d3, i32 %x, i32 0
  %r = sext i32 %s to i64
  ret i64 %r
}

attributes #0 = { nocallback nofree nosync nounwind willreturn memory(inaccessiblemem: write) }
