// DOM操作の小さな共通ヘルパー。
// createElementはユーザー由来の文字列を必ずtextContentで設定するための入口にし、
// innerHTMLへの文字列連結(XSSの典型的な原因)をアプリコード側から排除する。

export function el(tag, { className, text, attrs } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text; // innerHTMLは使わない
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  }
  for (const child of children) node.appendChild(child);
  return node;
}

let toastTimer = null;

export function showToast(message) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = el("div", { attrs: { id: "toast" } });
    document.body.appendChild(toast);
  }
  toast.textContent = message; // ここもtextContent(サーバーからのメッセージをそのまま表示するため)
  toast.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add("hidden"), 4000);
}

export function qs(selector, root = document) {
  return root.querySelector(selector);
}
