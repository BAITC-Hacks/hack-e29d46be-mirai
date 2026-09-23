/* Localized request failures shared by graph loading, cards and chat. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MiraiHttp = api;
})(typeof window === "undefined" ? globalThis : window, function () {
  "use strict";
  function createRequest(fetcher, timeoutMs = 30000) {
    return async function request(path, options = {}) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        let response;
        try {
          response = await fetcher(path, {...options, signal: controller.signal});
        } catch (error) {
          if (controller.signal.aborted || error.name === "AbortError")
            throw new Error("Время ожидания истекло. Повторите запрос.");
          throw new Error("Нет связи с локальным сервером. Проверьте, что Mirai запущен, и повторите запрос.");
        }
        let data;
        try { data = await response.json(); }
        catch {
          if (controller.signal.aborted)
            throw new Error("Время ожидания истекло. Повторите запрос.");
          throw new Error("Сервер вернул некорректный ответ. Повторите запрос.");
        }
        if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail :
          "Не удалось выполнить запрос. Повторите попытку.");
        return data;
      } finally { clearTimeout(timer); }
    };
  }
  return {createRequest};
});
