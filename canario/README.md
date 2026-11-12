# Canario

Documento fijo que recorre cada noche la cadena lector → formalizador → crítico → validación para comprobar que sigue funcionando; no es una recomendación ni una estrategia candidata.

Solo el dueño cambia `documento.md` y `esperado.json`; nadie más los toca.

Un canario que falla significa "se ha roto algo nuestro", no "el material era malo".

`extracto.mercado_contiene` acepta una cadena o una lista de cadenas; pasa si cualquiera de los valores esta en `extracto["mercado"]`.
