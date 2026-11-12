(function () {
  var nodo = document.getElementById("graficos-datos");
  if (!nodo || !window.LightweightCharts) return;
  var specs = JSON.parse(nodo.textContent);
  var css = getComputedStyle(document.documentElement);
  var token = function (n) { return css.getPropertyValue("--" + n).trim() || n; };
  var velo = function (n, a) {
    var h = token(n);
    if (h[0] !== "#" || h.length !== 7) return h;
    return "rgba(" + parseInt(h.slice(1, 3), 16) + "," + parseInt(h.slice(3, 5), 16) + "," + parseInt(h.slice(5, 7), 16) + "," + a + ")";
  };
  var num = function (v) { return v.toLocaleString("es-ES", {minimumFractionDigits: 2, maximumFractionDigits: 2}); };
  var creados = {}, periodo = 0;
  var madrid = function (o) { return new Intl.DateTimeFormat("es-ES", Object.assign({timeZone: "Europe/Madrid"}, o)); };
  var fHora = madrid({hour: "2-digit", minute: "2-digit"}), fDia = madrid({day: "numeric"}), fMes = madrid({month: "short"});
  var fAnio = madrid({year: "numeric"}), fTodo = madrid({day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"});
  var fecha = function (t) {
    if (typeof t === "string") return new Date(t + "T12:00:00Z");
    if (typeof t === "object") return new Date(Date.UTC(t.year, t.month - 1, t.day, 12));
    return new Date(t * 1000);
  };
  var marca = function (t, tipo) {
    var d = fecha(t);
    return tipo === 0 ? fAnio.format(d) : tipo === 1 ? fMes.format(d) : tipo === 2 ? fDia.format(d) : fHora.format(d);
  };

  function recorte(datos, spec) {
    if (!spec.periodos || !periodo || !datos.length) return datos;
    var corte = datos[datos.length - 1].time - periodo * 86400;
    return datos.filter(function (p) { return p.time >= corte; });
  }

  function pintar(obj) {
    obj.series.forEach(function (x) {
      var datos = recorte(x.spec.datos || [], obj.spec);
      if (x.spec.tipo === "histograma") {
        datos = datos.map(function (p) { return p.color ? {time: p.time, value: p.value, color: velo(p.color, 0.35)} : p; });
      }
      x.serie.setData(datos);
      if (x.spec.marcas) {
        var desde = datos.length ? datos[0].time : 0;
        x.serie.setMarkers(x.spec.marcas.filter(function (m) { return m.time >= desde; }).map(function (m) {
          return {time: m.time, position: m.position, shape: m.shape, text: m.text, color: token(m.color || "acento")};
        }));
      }
    });
    obj.grafico.timeScale().fitContent();
  }

  function crear(spec) {
    var el = document.getElementById(spec.id);
    if (!el) return null;
    var g = LightweightCharts.createChart(el, {
      autoSize: true,
      layout: {attributionLogo: false, background: {color: "transparent"}, textColor: token("tinta-suave"), fontFamily: token("fuente")},
      grid: {vertLines: {color: token("linea")}, horzLines: {color: token("linea")}},
      rightPriceScale: {borderColor: token("linea")},
      timeScale: {borderColor: token("linea"), timeVisible: true, tickMarkFormatter: marca},
      crosshair: {mode: 0, vertLine: {color: token("linea-clara"), labelBackgroundColor: token("superficie-alta")},
                  horzLine: {color: token("linea-clara"), labelBackgroundColor: token("superficie-alta")}},
      localization: {locale: "es-ES", priceFormatter: num, timeFormatter: function (t) { return typeof t === "number" ? fTodo.format(fecha(t)) : fDia.format(fecha(t)) + " " + fMes.format(fecha(t)); }}
    });
    var series = (spec.series || []).map(function (s) {
      var col = s.color || "acento", serie, o;
      if (s.tipo === "area") {
        serie = g.addAreaSeries({lineColor: token(col), topColor: velo(col, 0.18), bottomColor: velo(col, 0), lineWidth: 2});
      } else if (s.tipo === "velas") {
        serie = g.addCandlestickSeries({upColor: token("sube"), downColor: token("baja"), borderVisible: false,
                                        wickUpColor: token("sube"), wickDownColor: token("baja")});
      } else if (s.tipo === "histograma") {
        o = {priceFormat: {type: "volume"}, color: velo(s.color || "linea-clara", 0.35)};
        if (s.escala_propia) o.priceScaleId = "";
        serie = g.addHistogramSeries(o);
        if (s.escala_propia) serie.priceScale().applyOptions({scaleMargins: {top: 0.8, bottom: 0}});
      } else {
        serie = g.addLineSeries({color: token(col), lineWidth: s.ancho || 1, lineStyle: s.discontinua ? 2 : 0,
                                 priceLineVisible: false, lastValueVisible: false});
      }
      return {spec: s, serie: serie};
    });
    if (series.length) {
      (spec.lineas || []).forEach(function (l) {
        series[0].serie.createPriceLine({price: l.valor, color: token(l.color || "linea-clara"), lineStyle: 2, lineWidth: 1, axisLabelVisible: false});
      });
    }
    var obj = {spec: spec, grafico: g, series: series};
    pintar(obj);
    return obj;
  }

  function visibles() {
    specs.forEach(function (spec) {
      var el = document.getElementById(spec.id);
      var caja = el && el.closest("[data-vista]");
      if (el && !creados[spec.id] && !(caja && caja.hidden)) {
        try { creados[spec.id] = crear(spec); } catch (e) { el.textContent = "No se pudo dibujar este gráfico."; }
      }
    });
  }

  document.querySelectorAll("[data-g]").forEach(function (b) {
    b.addEventListener("click", function () {
      var zona = b.closest("section") || document;
      var v = b.getAttribute("data-g");
      zona.querySelectorAll("[data-g]").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      zona.querySelectorAll("[data-vista]").forEach(function (x) { x.hidden = x.getAttribute("data-vista") !== v; });
      zona.querySelectorAll("[data-solo]").forEach(function (x) { x.hidden = x.getAttribute("data-solo") !== v; });
      visibles();
    });
  });
  document.querySelectorAll("[data-p]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (b.disabled) return;
      document.querySelectorAll("[data-p]").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      periodo = +b.getAttribute("data-p");
      Object.keys(creados).forEach(function (k) { if (creados[k] && creados[k].spec.periodos) pintar(creados[k]); });
    });
  });
  visibles();
})();
