# T25 · Torneo de pronósticos -- 5 algoritmos, backtest rolling-origin (h=1..3)

Waykee 290123. DB: `/private/tmp/v2/comprasai.db`. Corte de datos: hasta `2026-07`.

**PRELIMINAR -- SIN CENSURA.** El dataset usado (`data-real-car-v2`) no trae `kardex_diario` todavía (release `data-real-car-v3`, T23 en curso). Ningún mes fue excluido por desabasto: la demanda observada en meses con quiebre real (si los hubo) se está tratando como demanda verdadera, lo que puede sesgar el WAPE hacia abajo en materiales con historial de quiebres. Re-correr este mismo script contra v3 en cuanto el kardex esté disponible.


## Nivel `canal`

Universo: 10197 pares material×canal. Se evaluaron los top **300** por valor (70.5% del valor total de ese universo).

Observaciones: 53460 generadas, 360 sin predicción (historia insuficiente para ese algoritmo), 0 censuradas por desabasto, **53100 usadas** para las métricas de abajo.


### WAPE / sesgo por algoritmo x horizonte

| algoritmo | horizonte | wape_pct | sesgo_pct | n_observaciones |
| --- | --- | --- | --- | --- |
| A1_seasonal_naive | 1 | 39.84 | 2.91 | 3550 |
| A2_media_movil_3m | 1 | 22.41 | 3.14 | 3550 |
| A3_tendencia_estacional | 1 | 27.85 | 7.55 | 3500 |
| A4_holt_winters | 1 | 41.54 | 13.65 | 3550 |
| A5_croston_sba | 1 | 34.04 | -5.85 | 3550 |
| A1_seasonal_naive | 2 | 43.08 | 3.97 | 3550 |
| A2_media_movil_3m | 2 | 25.38 | 4.44 | 3550 |
| A3_tendencia_estacional | 2 | 32.06 | 10.69 | 3500 |
| A4_holt_winters | 2 | 47.24 | 19.96 | 3550 |
| A5_croston_sba | 2 | 36.73 | -4.67 | 3550 |
| A1_seasonal_naive | 3 | 45.83 | 6.62 | 3550 |
| A2_media_movil_3m | 3 | 28.34 | 6.04 | 3550 |
| A3_tendencia_estacional | 3 | 36.37 | 14.37 | 3500 |
| A4_holt_winters | 3 | 53.13 | 27.33 | 3550 |
| A5_croston_sba | 3 | 39.07 | -3.2 | 3550 |


**Ganador por horizonte (menor WAPE, min. 30 observaciones):**

- h=1: `A2_media_movil_3m` (WAPE 22.41%, sesgo 3.14%, n=3550)

- h=2: `A2_media_movil_3m` (WAPE 25.38%, sesgo 4.44%, n=3550)

- h=3: `A2_media_movil_3m` (WAPE 28.34%, sesgo 6.04%, n=3550)


### WAPE por algoritmo x horizonte x ABC

| algoritmo | horizonte | abc | wape_pct | sesgo_pct | n_observaciones |
| --- | --- | --- | --- | --- | --- |
| A1_seasonal_naive | 1 | A | 39.84 | 2.91 | 3550 |
| A2_media_movil_3m | 1 | A | 22.41 | 3.14 | 3550 |
| A3_tendencia_estacional | 1 | A | 27.85 | 7.55 | 3500 |
| A4_holt_winters | 1 | A | 41.54 | 13.65 | 3550 |
| A5_croston_sba | 1 | A | 34.04 | -5.85 | 3550 |
| A1_seasonal_naive | 2 | A | 43.08 | 3.97 | 3550 |
| A2_media_movil_3m | 2 | A | 25.38 | 4.44 | 3550 |
| A3_tendencia_estacional | 2 | A | 32.06 | 10.69 | 3500 |
| A4_holt_winters | 2 | A | 47.24 | 19.96 | 3550 |
| A5_croston_sba | 2 | A | 36.73 | -4.67 | 3550 |
| A1_seasonal_naive | 3 | A | 45.83 | 6.62 | 3550 |
| A2_media_movil_3m | 3 | A | 28.34 | 6.04 | 3550 |
| A3_tendencia_estacional | 3 | A | 36.37 | 14.37 | 3500 |
| A4_holt_winters | 3 | A | 53.13 | 27.33 | 3550 |
| A5_croston_sba | 3 | A | 39.07 | -3.2 | 3550 |


### WAPE por algoritmo x familia (top 8 familias por volumen de observaciones -- tabla completa en el JSON)

| algoritmo | familia | wape_pct | sesgo_pct | n_observaciones |
| --- | --- | --- | --- | --- |
| A1_seasonal_naive | CASSABELLA | 96.51 | -9.72 | 36 |
| A2_media_movil_3m | CASSABELLA | 105.52 | 9.19 | 36 |
| A3_tendencia_estacional | CASSABELLA | 129.27 | -5.94 | 36 |
| A4_holt_winters | CASSABELLA | 125.95 | 118.12 | 36 |
| A5_croston_sba | CASSABELLA | 102.69 | 3.91 | 36 |
| A1_seasonal_naive | DURATILE | 87.83 | -8.09 | 1296 |
| A2_media_movil_3m | DURATILE | 30.86 | 2.59 | 1296 |
| A3_tendencia_estacional | DURATILE | 33.13 | 17.73 | 1281 |
| A4_holt_winters | DURATILE | 56.14 | 20.45 | 1296 |
| A5_croston_sba | DURATILE | 71.47 | -13.69 | 1296 |
| A1_seasonal_naive | MERCANTIL | 155.41 | 136.42 | 30 |
| A2_media_movil_3m | MERCANTIL | 113.27 | 92.25 | 30 |
| A3_tendencia_estacional | MERCANTIL | 109.32 | 34.78 | 18 |
| A4_holt_winters | MERCANTIL | 308.29 | 304.66 | 30 |
| A5_croston_sba | MERCANTIL | 146.83 | 112.76 | 30 |
| A1_seasonal_naive | PORCELANITE | 36.28 | 5.04 | 9180 |
| A2_media_movil_3m | PORCELANITE | 24.02 | 4.31 | 9180 |
| A3_tendencia_estacional | PORCELANITE | 31.38 | 9.81 | 9063 |
| A4_holt_winters | PORCELANITE | 44.96 | 18.81 | 9180 |
| A5_croston_sba | PORCELANITE | 31.41 | -4.28 | 9180 |
| A1_seasonal_naive | QUALITY | 159.63 | 148.68 | 108 |
| A2_media_movil_3m | QUALITY | 79.55 | 60.71 | 108 |
| A3_tendencia_estacional | QUALITY | 82.13 | 48.06 | 102 |
| A4_holt_winters | QUALITY | 153.39 | 152.83 | 108 |
| A5_croston_sba | QUALITY | 121.57 | 103.94 | 108 |


## Nivel `sucursal`

Universo: 208578 pares material×sucursal. Se evaluaron los top **30000** por valor (84.6% del valor total de ese universo).

Observaciones: 3991665 generadas, 702885 sin predicción (historia insuficiente para ese algoritmo), 0 censuradas por desabasto, **3288780 usadas** para las métricas de abajo.


### WAPE / sesgo por algoritmo x horizonte

| algoritmo | horizonte | wape_pct | sesgo_pct | n_observaciones |
| --- | --- | --- | --- | --- |
| A1_seasonal_naive | 1 | 85.85 | 2.1 | 232329 |
| A2_media_movil_3m | 1 | 77.19 | 2.01 | 232329 |
| A3_tendencia_estacional | 1 | 80.35 | -3.65 | 166944 |
| A4_holt_winters | 1 | 136.66 | 47.74 | 232329 |
| A5_croston_sba | 1 | 75.43 | -4.32 | 232329 |
| A1_seasonal_naive | 2 | 87.86 | 2.61 | 232329 |
| A2_media_movil_3m | 2 | 78.39 | 2.78 | 232329 |
| A3_tendencia_estacional | 2 | 84.54 | -0.89 | 166944 |
| A4_holt_winters | 2 | 160.61 | 71.53 | 232329 |
| A5_croston_sba | 2 | 76.45 | -3.6 | 232329 |
| A1_seasonal_naive | 3 | 90.69 | 4.59 | 232329 |
| A2_media_movil_3m | 3 | 80.13 | 4.48 | 232329 |
| A3_tendencia_estacional | 3 | 89.1 | 2.94 | 166944 |
| A4_holt_winters | 3 | 187.12 | 98.21 | 232329 |
| A5_croston_sba | 3 | 78.07 | -2.0 | 232329 |


**Ganador por horizonte (menor WAPE, min. 30 observaciones):**

- h=1: `A5_croston_sba` (WAPE 75.43%, sesgo -4.32%, n=232329)

- h=2: `A5_croston_sba` (WAPE 76.45%, sesgo -3.6%, n=232329)

- h=3: `A5_croston_sba` (WAPE 78.07%, sesgo -2.0%, n=232329)


### WAPE por algoritmo x horizonte x ABC

| algoritmo | horizonte | abc | wape_pct | sesgo_pct | n_observaciones |
| --- | --- | --- | --- | --- | --- |
| A1_seasonal_naive | 1 | A | 85.59 | 1.85 | 217936 |
| A2_media_movil_3m | 1 | A | 76.76 | 1.87 | 217936 |
| A3_tendencia_estacional | 1 | A | 80.15 | -3.62 | 159446 |
| A4_holt_winters | 1 | A | 135.17 | 46.43 | 217936 |
| A5_croston_sba | 1 | A | 74.83 | -4.68 | 217936 |
| A1_seasonal_naive | 1 | B | 91.83 | 7.85 | 13116 |
| A2_media_movil_3m | 1 | B | 87.17 | 5.04 | 13116 |
| A3_tendencia_estacional | 1 | B | 87.98 | -4.97 | 6991 |
| A4_holt_winters | 1 | B | 171.94 | 79.64 | 13116 |
| A5_croston_sba | 1 | B | 88.73 | 3.56 | 13116 |
| A1_seasonal_naive | 1 | C | 91.81 | 9.01 | 1277 |
| A2_media_movil_3m | 1 | C | 90.31 | 7.93 | 1277 |
| A3_tendencia_estacional | 1 | C | 90.28 | -2.89 | 507 |
| A4_holt_winters | 1 | C | 168.78 | 66.46 | 1277 |
| A5_croston_sba | 1 | C | 99.17 | 12.51 | 1277 |
| A1_seasonal_naive | 2 | A | 87.54 | 2.27 | 217936 |
| A2_media_movil_3m | 2 | A | 77.92 | 2.57 | 217936 |
| A3_tendencia_estacional | 2 | A | 84.3 | -0.92 | 159446 |
| A4_holt_winters | 2 | A | 158.23 | 69.35 | 217936 |
| A5_croston_sba | 2 | A | 75.8 | -4.03 | 217936 |
| A1_seasonal_naive | 2 | B | 95.44 | 10.93 | 13116 |
| A2_media_movil_3m | 2 | B | 89.44 | 7.83 | 13116 |
| A3_tendencia_estacional | 2 | B | 94.14 | -0.09 | 6991 |
| A4_holt_winters | 2 | B | 218.15 | 125.35 | 13116 |
| A5_croston_sba | 2 | B | 91.4 | 6.31 | 13116 |
| A1_seasonal_naive | 2 | C | 96.02 | 9.02 | 1277 |
| A2_media_movil_3m | 2 | C | 91.99 | 6.73 | 1277 |
| A3_tendencia_estacional | 2 | C | 99.24 | 5.87 | 507 |
| A4_holt_winters | 2 | C | 211.49 | 104.8 | 1277 |
| A5_croston_sba | 2 | C | 98.93 | 11.24 | 1277 |
| A1_seasonal_naive | 3 | A | 90.26 | 4.09 | 217936 |
| A2_media_movil_3m | 3 | A | 79.59 | 4.14 | 217936 |
| A3_tendencia_estacional | 3 | A | 88.79 | 2.85 | 159446 |
| A4_holt_winters | 3 | A | 183.6 | 94.94 | 217936 |
| A5_croston_sba | 3 | A | 77.34 | -2.56 | 217936 |
| A1_seasonal_naive | 3 | B | 101.66 | 16.87 | 13116 |
| A2_media_movil_3m | 3 | B | 93.68 | 12.86 | 13116 |
| A3_tendencia_estacional | 3 | B | 101.69 | 6.49 | 6991 |
| A4_holt_winters | 3 | B | 274.78 | 180.49 | 13116 |
| A5_croston_sba | 3 | B | 95.67 | 11.26 | 13116 |
| A1_seasonal_naive | 3 | C | 98.2 | 18.16 | 1277 |
| A2_media_movil_3m | 3 | C | 92.23 | 15.95 | 1277 |
| A3_tendencia_estacional | 3 | C | 104.65 | 15.68 | 507 |
| A4_holt_winters | 3 | C | 270.52 | 166.94 | 1277 |
| A5_croston_sba | 3 | C | 101.97 | 20.85 | 1277 |


### WAPE por algoritmo x familia (top 8 familias por volumen de observaciones -- tabla completa en el JSON)

| algoritmo | familia | wape_pct | sesgo_pct | n_observaciones |
| --- | --- | --- | --- | --- |
| A1_seasonal_naive | ALAPLANA | 97.75 | 12.27 | 972 |
| A2_media_movil_3m | ALAPLANA | 99.14 | 17.94 | 972 |
| A3_tendencia_estacional | ALAPLANA | 96.88 | 1.75 | 561 |
| A4_holt_winters | ALAPLANA | 195.71 | 99.22 | 972 |
| A5_croston_sba | ALAPLANA | 92.73 | 4.08 | 972 |
| A1_seasonal_naive | CASSABELLA | 104.67 | 5.26 | 1719 |
| A2_media_movil_3m | CASSABELLA | 101.45 | 2.73 | 1719 |
| A3_tendencia_estacional | CASSABELLA | 100.5 | -26.59 | 660 |
| A4_holt_winters | CASSABELLA | 371.52 | 282.76 | 1719 |
| A5_croston_sba | CASSABELLA | 93.2 | -1.37 | 1719 |
| A1_seasonal_naive | DURATILE | 79.88 | -13.58 | 60345 |
| A2_media_movil_3m | DURATILE | 72.23 | -1.85 | 60345 |
| A3_tendencia_estacional | DURATILE | 76.97 | -1.83 | 41532 |
| A4_holt_winters | DURATILE | 138.21 | 49.18 | 60345 |
| A5_croston_sba | DURATILE | 72.05 | -17.19 | 60345 |
| A1_seasonal_naive | GAYAF | 101.32 | 11.09 | 5718 |
| A2_media_movil_3m | GAYAF | 88.56 | 4.47 | 5718 |
| A3_tendencia_estacional | GAYAF | 93.22 | -6.83 | 4350 |
| A4_holt_winters | GAYAF | 198.18 | 103.89 | 5718 |
| A5_croston_sba | GAYAF | 85.52 | 4.01 | 5718 |
| A1_seasonal_naive | LAMOR | 98.97 | 10.59 | 2841 |
| A2_media_movil_3m | LAMOR | 92.6 | 9.3 | 2841 |
| A3_tendencia_estacional | LAMOR | 98.62 | 0.89 | 1248 |
| A4_holt_winters | LAMOR | 309.36 | 223.12 | 2841 |
| A5_croston_sba | LAMOR | 96.05 | 8.07 | 2841 |
| A1_seasonal_naive | NEXO | 92.08 | 2.43 | 2892 |
| A2_media_movil_3m | NEXO | 80.65 | -2.15 | 2892 |
| A3_tendencia_estacional | NEXO | 83.51 | -9.14 | 1863 |
| A4_holt_winters | NEXO | 188.46 | 84.06 | 2892 |
| A5_croston_sba | NEXO | 99.58 | 14.78 | 2892 |
| A1_seasonal_naive | PORCELANITE | 88.7 | 4.82 | 607122 |
| A2_media_movil_3m | PORCELANITE | 78.78 | 3.49 | 607122 |
| A3_tendencia_estacional | PORCELANITE | 85.26 | -0.3 | 443946 |
| A4_holt_winters | PORCELANITE | 161.26 | 72.62 | 607122 |
| A5_croston_sba | PORCELANITE | 76.55 | -2.06 | 607122 |
| A1_seasonal_naive | QUALITY | 102.51 | 17.98 | 12594 |
| A2_media_movil_3m | QUALITY | 98.16 | 14.36 | 12594 |
| A3_tendencia_estacional | QUALITY | 98.67 | -4.03 | 5763 |
| A4_holt_winters | QUALITY | 238.36 | 137.1 | 12594 |
| A5_croston_sba | QUALITY | 99.19 | 16.09 | 12594 |


## Simulación de servicio (cobertura objetivo, nivel sucursal)

Simulación SIMPLIFICADA (sin RN-02/transferencias, lead time <= 1 mes -- ver limitaciones en el docstring del módulo). 29011 series material×sucursal simuladas. Baseline = `A2_media_movil_3m` (motor C1 vigente hoy).

| algoritmo | quiebres | meses_simulados | tasa_quiebre_pct | quiebres_vs_baseline | pedidos_totales_cajas |
| --- | --- | --- | --- | --- | --- |
| A1_seasonal_naive | 38468 | 266111 | 14.46 | 1499 | 8161630.0 |
| A2_media_movil_3m | 36969 | 266111 | 13.89 | 0 | 7927712.0 |
| A3_tendencia_estacional | 43697 | 266111 | 16.42 | 6728 | 7733376.0 |
| A4_holt_winters | 51760 | 266111 | 19.45 | 14791 | 8486006.0 |
| A5_croston_sba | 42553 | 266111 | 15.99 | 5584 | 7443854.0 |


## Estacionalidad por familia (agregado, universo completo)

Universo: 125 familias con ventas en el periodo. 100 NO se pudieron evaluar (< 12 meses distintos con venta o historia insuficiente para ajustar tendencia+estacionalidad) -- quedan excluidas del análisis, no contadas como 'no significativas'.

De las 25 familias SÍ evaluadas: 25 (swing pico-valle >= 8.0% del nivel medio) muestran estacionalidad SIGNIFICATIVA; 0 no la muestran.

De esas 25 significativas, 24 tienen volumen robusto (nivel medio >= 10 m2/mes, mismo piso que RN-16/GANADOR_BASE_MINIMA_M2 del motor C2) y son lectura confiable; las 1 restantes tienen nivel medio por debajo de ese piso -- swings de cientos de % ahí son más probablemente efecto de base pequeña (ruido) que un patrón comercial real, y se listan aparte para no confundirlas con las señales fuertes (p.ej. PORCELANATO, FIREN, AZUVI, GREDA).


**Familias con volumen robusto (lectura confiable), ordenadas por swing:**

| familia | nivel_medio_m2 | mes_pico | efecto_pico_pct | mes_valle | efecto_valle_pct | swing_pct | tendencia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OBSOLETOS | 11.1 | 11 | 620.0 | 7 | -123.6 | 743.6 | estable |
| MERCANTIL | 2296.4 | 8 | 294.8 | 4 | -86.3 | 381.0 | estable |
| CASSABELLA | 4593.5 | 8 | 190.2 | 12 | -71.1 | 261.2 | decreciente |
| TENDENZZA | 1172.2 | 5 | 157.7 | 8 | -100.0 | 257.7 | creciente |
| NIRO | 12.7 | 3 | 195.5 | 4 | -52.6 | 248.1 | estable |
| GREDA | 874.3 | 9 | 103.5 | 12 | -63.2 | 166.7 | decreciente |
| AZUVI | 360.4 | 11 | 108.6 | 12 | -44.6 | 153.1 | estable |
| LETSA | 297.2 | 11 | 79.4 | 5 | -51.5 | 130.8 | creciente |
| APE | 149.0 | 9 | 72.7 | 8 | -52.6 | 125.2 | decreciente |
| FIREN | 6715.4 | 11 | 75.2 | 8 | -42.4 | 117.7 | creciente |
| ISTONE | 125.7 | 10 | 75.7 | 1 | -37.5 | 113.1 | estable |
| NEW TILE | 224.3 | 2 | 68.1 | 10 | -43.5 | 111.5 | creciente |
| PERON | 353.4 | 11 | 71.6 | 4 | -36.8 | 108.4 | decreciente |
| PORCELANATO | 7875.0 | 6 | 67.9 | 2 | -36.8 | 104.7 | creciente |
| NEXO | 3659.8 | 6 | 42.7 | 12 | -56.6 | 99.3 | decreciente |


**Familias de base pequeña (swings grandes probablemente ruido, NO tratar como señal comercial fuerte):**

| familia | nivel_medio_m2 | mes_pico | efecto_pico_pct | mes_valle | efecto_valle_pct | swing_pct | tendencia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EVERS | 1.3 | 5 | 683.6 | 7 | -198.9 | 882.5 | estable |
