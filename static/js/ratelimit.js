/**
 * ratelimit.js — feedback, kontakt va cofe formalari uchun UMUMIY cheklov holati.
 *
 * Bitta localStorage kaliti orqali barcha sahifalar (feedback widget, /kontakt,
 * /cofe) bir xil "25 daqiqada 2 ta so'rov" holatini ko'radi, shu sababli
 * sahifani yangilash (F5) cheklovni "ochib yubormaydi".
 *
 * Haqiqiy server tomonidagi oyna 20-25 daqiqa orasida tasodifiy bo'ladi
 * (bot/avtomatlashtirishga qarshi), lekin foydalanuvchiga har doim ENG
 * KATTA qiymat — 25 daqiqa — ko'rsatiladi. Shu sababli mijoz tomonidagi
 * hisoblagich tugaganda server oynasi ham albatta tugagan bo'ladi.
 */
(function (global) {
  var KEY = "wh_rl_v1";
  var MAX_COUNT = 2;
  var DISPLAY_MS = 25 * 60 * 1000; // foydalanuvchiga har doim shu ko'rsatiladi

  function readState() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return null;
      var s = JSON.parse(raw);
      if (typeof s.count !== "number" || typeof s.start !== "number") return null;
      return s;
    } catch (e) {
      return null;
    }
  }

  function writeState(state) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
  }

  function clearState() {
    try { localStorage.removeItem(KEY); } catch (e) {}
  }

  function activeState() {
    var s = readState();
    if (!s) return null;
    if (Date.now() - s.start >= DISPLAY_MS) {
      clearState();
      return null;
    }
    return s;
  }

  function isLocked() {
    var s = activeState();
    return !!s && s.count >= MAX_COUNT;
  }

  function remainingMs() {
    var s = activeState();
    if (!s) return 0;
    var left = DISPLAY_MS - (Date.now() - s.start);
    return left > 0 ? left : 0;
  }

  // Muvaffaqiyatli yuborishdan keyin chaqiriladi.
  function recordAttempt() {
    var s = activeState();
    if (!s) {
      s = { count: 1, start: Date.now() };
    } else {
      s.count += 1;
    }
    writeState(s);
  }

  // Server 429 (limit) qaytarsa chaqiriladi — mijoz holatini darhol
  // to'liq 25 daqiqalik qulflashga majburlaydi.
  function forceLock() {
    writeState({ count: MAX_COUNT, start: Date.now() });
  }

  function formatTime(ms) {
    var total = Math.ceil(ms / 1000);
    var m = Math.floor(total / 60);
    var s = total % 60;
    return (m < 10 ? "0" + m : m) + ":" + (s < 10 ? "0" + s : s);
  }

  global.WHRateLimit = {
    isLocked: isLocked,
    remainingMs: remainingMs,
    recordAttempt: recordAttempt,
    forceLock: forceLock,
    formatTime: formatTime,
  };
})(window);
