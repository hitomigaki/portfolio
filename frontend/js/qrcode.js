// frontend/js/vendor/qrcode-generator.js (MITライセンス) の薄いラッパー。
// ライブラリ本体はQRのビット列をSVGの矩形として描画するだけで、
// 渡した文字列をHTMLとして解釈することはない(XSSの心配がない)。

export function renderQrCode(container, text) {
  container.innerHTML = "";
  const qr = window.qrcode(0, "M"); // typeNumber=0で自動選択, 誤り訂正レベルM
  qr.addData(text);
  qr.make();
  container.innerHTML = qr.createSvgTag({ scalable: true });
}
