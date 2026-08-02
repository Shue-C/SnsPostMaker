/**
 * 抽選ロジック。
 *
 *   bag      … 全種を袋に入れて引いていく方式。1周するまで同じものが出ない。
 *               イベントで「大吉ばかり／凶ばかり」の偏りが出にくい。
 *   weighted … 毎回独立の重み付き抽選。
 *
 * bag の残りは localStorage に保存するので、ブラウザを再読み込みしても
 * 引き途中の状態が続く（設定パネルからリセット可）。
 */
(function (global) {
  'use strict';

  var STORAGE_KEY = 'omikuji.bag.v1';

  /** 暗号論的乱数で 0..n-1 を返す（Math.random の偏りを避ける）。 */
  function randomInt(n) {
    if (global.crypto && global.crypto.getRandomValues) {
      var limit = Math.floor(0xffffffff / n) * n;
      var buf = new Uint32Array(1);
      do { global.crypto.getRandomValues(buf); } while (buf[0] >= limit);
      return buf[0] % n;
    }
    return Math.floor(Math.random() * n);
  }

  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = randomInt(i + 1);
      var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }

  function Drawer(items, mode) {
    this.items = items;
    this.mode = mode === 'weighted' ? 'weighted' : 'bag';
    this.lastId = null;
    this.bag = this._restore();
  }

  Drawer.prototype._restore = function () {
    try {
      var saved = JSON.parse(global.localStorage.getItem(STORAGE_KEY));
      if (Array.isArray(saved) && saved.length) {
        var valid = {};
        this.items.forEach(function (it) { valid[it.id] = true; });
        var filtered = saved.filter(function (id) { return valid[id]; });
        if (filtered.length) return filtered;
      }
    } catch (e) { /* 壊れていたら作り直す */ }
    return [];
  };

  Drawer.prototype._persist = function () {
    try {
      global.localStorage.setItem(STORAGE_KEY, JSON.stringify(this.bag));
    } catch (e) { /* プライベートブラウズ等では保存できないが動作に支障は無い */ }
  };

  Drawer.prototype._refill = function () {
    var ids = [];
    this.items.forEach(function (it) {
      var copies = Math.max(1, Math.round(it.weight || 1));
      for (var i = 0; i < copies; i++) ids.push(it.id);
    });
    shuffle(ids);
    // 袋を入れ替えた直後に同じものが連続しないようにする
    if (ids.length > 1 && ids[ids.length - 1] === this.lastId) {
      var t = ids[ids.length - 1];
      ids[ids.length - 1] = ids[0];
      ids[0] = t;
    }
    this.bag = ids;
  };

  Drawer.prototype._byId = function (id) {
    for (var i = 0; i < this.items.length; i++) {
      if (this.items[i].id === id) return this.items[i];
    }
    return this.items[0];
  };

  Drawer.prototype.draw = function () {
    if (this.mode === 'weighted') {
      var total = 0;
      this.items.forEach(function (it) { total += Math.max(0, it.weight || 1); });
      var r = randomInt(Math.max(1, Math.round(total * 1000))) / 1000;
      var acc = 0;
      for (var i = 0; i < this.items.length; i++) {
        acc += Math.max(0, this.items[i].weight || 1);
        if (r < acc) { this.lastId = this.items[i].id; return this.items[i]; }
      }
      this.lastId = this.items[this.items.length - 1].id;
      return this.items[this.items.length - 1];
    }

    if (!this.bag.length) this._refill();
    var id = this.bag.pop();
    this._persist();
    this.lastId = id;
    return this._byId(id);
  };

  /** 袋の残り枚数。空なら「次に補充される枚数」を返す（表示用）。 */
  Drawer.prototype.remaining = function () {
    if (this.mode !== 'bag') return null;
    if (this.bag.length) return this.bag.length;
    var total = 0;
    this.items.forEach(function (it) { total += Math.max(1, Math.round(it.weight || 1)); });
    return total;
  };

  Drawer.prototype.reset = function () {
    this.bag = [];
    this.lastId = null;
    this._persist();
  };

  global.Drawer = Drawer;
})(window);
