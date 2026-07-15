# 保留 JS 桥接口，避免 release 混淆后网页调用 window.Android.printPhoto 失效
-keepclassmembers class com.leshine.expokiosk.MainActivity$WebBridge {
   public *;
}
