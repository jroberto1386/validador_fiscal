# ==============================================================================
# app.py - Servidor Backend para el Validador Fiscal Inteligente
# ==============================================================================
# Este script crea una aplicación web simple utilizando Flask.
# Su propósito es recibir un archivo Excel, procesar sus hojas de cálculo
# con pandas, ejecutar una serie de validaciones fiscales y mostrar
# los resultados en una página web.
# ==============================================================================

# --- 1. Importación de Librerías ---
# Importamos las herramientas necesarias para nuestro proyecto.
import pandas as pd
from flask import Flask, render_template, request

# --- 2. Inicialización de la Aplicación ---
# Creamos la instancia principal de nuestra aplicación web Flask.
app = Flask(__name__)

# --- 3. Lógica Central de Validación ---
# Esta función es el cerebro de la aplicación. Recibe los datos del Excel
# y ejecuta todas las revisiones lógicas.
def ejecutar_validaciones(df_isr, df_facturacion, df_resumen, df_iva):
    """
    Analiza los DataFrames extraídos del Excel y realiza 4 validaciones clave.
    
    Args:
        df_isr (pd.DataFrame): Datos de la hoja "Calculo ISR".
        df_facturacion (pd.DataFrame): Datos de la hoja "Facturacion".
        df_resumen (pd.DataFrame): Datos de la hoja "RESUMEN".
        df_iva (pd.DataFrame): Datos de la hoja "Calculo IVA".

    Returns:
        list: Una lista de diccionarios, donde cada diccionario representa
              el resultado de una validación.
    """
    resultados = []
    
    # Para este demo, nos enfocamos en los meses con datos: Junio (6) y Julio (7).
    # En una versión real, esto iteraría por todos los meses con ingresos.
    meses_a_validar = ['6', '7']
    
    # --- CORRECCIÓN APLICADA AQUÍ ---
    # Convertimos los nombres de las columnas a tipo string para evitar errores.
    df_isr.columns = df_isr.columns.map(str)
    df_iva.columns = df_iva.columns.map(str)
    
    for mes_idx in meses_a_validar:
        # Extraemos los ingresos del mes actual del cálculo de ISR
        ingresos_calculo = df_isr.loc['Ingresos cobrados del mes', mes_idx]
        
        # Si no hay ingresos en el mes, saltamos a la siguiente iteración
        if ingresos_calculo == 0:
            continue

        # --- Validación 1: Conciliación de Ingresos ---
        try:
            # Filtramos las facturas del mes correspondiente que estén vigentes
            facturas_mes = df_facturacion[df_facturacion['Mes'] == int(mes_idx)]
            ingresos_facturas = facturas_mes[facturas_mes['Estado SAT'] == 'Vigente']['SubTotal'].sum()
            
            # Comparamos los ingresos del cálculo con la suma de las facturas
            if abs(ingresos_calculo - ingresos_facturas) < 0.01: # Usamos tolerancia para decimales
                resultados.append({'id': 1, 'punto': f'Conciliación de Ingresos (Mes {mes_idx})', 'status': '✅ Correcto', 'obs': f'Los ingresos (${ingresos_calculo:,.2f}) coinciden con los CFDI.'})
            else:
                resultados.append({'id': 1, 'punto': f'Conciliación de Ingresos (Mes {mes_idx})', 'status': '❌ Error', 'obs': f'Ingresos del cálculo (${ingresos_calculo:,.2f}) no coinciden con los CFDI (${ingresos_facturas:,.2f}).'})
        except Exception as e:
            resultados.append({'id': 1, 'punto': f'Conciliación de Ingresos (Mes {mes_idx})', 'status': '⚠️ Advertencia', 'obs': f'No se pudo realizar la validación. Error: {e}'})

        # --- Validación 2: IVA Exento (Lógica de Negocio) ---
        try:
            iva_a_cargo = df_iva.loc['IVA a cargo (a favor)', mes_idx]
            if iva_a_cargo == 0:
                 resultados.append({'id': 2, 'punto': f'Validación de IVA Exento (Mes {mes_idx})', 'status': '✅ Correcto', 'obs': 'El IVA a cargo es $0.00, acorde a la actividad exenta (Arrendamiento Casa Habitación).'})
            else:
                 resultados.append({'id': 2, 'punto': f'Validación de IVA Exento (Mes {mes_idx})', 'status': '❌ Error', 'obs': f'Se calculó un IVA a cargo de ${iva_a_cargo:,.2f} para una actividad exenta.'})
        except Exception as e:
            resultados.append({'id': 2, 'punto': f'Validación de IVA Exento (Mes {mes_idx})', 'status': '⚠️ Advertencia', 'obs': f'No se pudo verificar el IVA. Error: {e}'})

        # --- Validación 3: Consistencia del Saldo a Pagar ---
        try:
            pago_calculo = df_isr.loc['Total a pagar', mes_idx]
            # Localizamos el valor en la hoja resumen por posición (fila 8, columna del mes)
            pago_resumen = df_resumen.iloc[7, 3 + int(mes_idx)]
            
            if abs(pago_calculo - pago_resumen) < 0.01:
                resultados.append({'id': 3, 'punto': f'Consistencia del Saldo a Pagar (Mes {mes_idx})', 'status': '✅ Correcto', 'obs': f'El saldo a pagar (${pago_calculo:,.2f}) es consistente en todos los cálculos.'})
            else:
                resultados.append({'id': 3, 'punto': f'Consistencia del Saldo a Pagar (Mes {mes_idx})', 'status': '❌ Error', 'obs': f'El pago del cálculo (${pago_calculo:,.2f}) no coincide con el resumen (${pago_resumen:,.2f}).'})
        except Exception as e:
            resultados.append({'id': 3, 'punto': f'Consistencia del Saldo a Pagar (Mes {mes_idx})', 'status': '⚠️ Advertencia', 'obs': f'No se pudo realizar la validación. Error: {e}'})
            
        # --- Validación 4: Verificación de Retenciones ---
        try:
            retencion_calculo = df_isr.loc['ISR retenido', mes_idx]
            # Sumamos las retenciones de facturas vigentes emitidas a Personas Morales (RFC de 12 posiciones)
            facturas_mes_vigentes = facturas_mes[facturas_mes['Estado SAT'] == 'Vigente']
            facturas_pm = facturas_mes_vigentes[facturas_mes_vigentes['RFC Receptor'].str.len() == 12]
            retencion_facturas = facturas_pm['Retenido ISR'].sum()
            
            if abs(retencion_calculo - retencion_facturas) < 0.01:
                resultados.append({'id': 4, 'punto': f'Verificación de Retenciones (Mes {mes_idx})', 'status': '✅ Correcto', 'obs': f'La retención (${retencion_calculo:,.2f}) es consistente con los CFDI.'})
            else:
                resultados.append({'id': 4, 'punto': f'Verificación de Retenciones (Mes {mes_idx})', 'status': '❌ Error', 'obs': f'La retención del cálculo (${retencion_calculo:,.2f}) no coincide con la de los CFDI (${retencion_facturas:,.2f}).'})
        except Exception as e:
            resultados.append({'id': 4, 'punto': f'Verificación de Retenciones (Mes {mes_idx})', 'status': '⚠️ Advertencia', 'obs': f'No se pudo realizar la validación. Error: {e}'})
            
    return resultados

# --- 4. Definición de Rutas de la Aplicación ---

# Ruta para la página principal ('/'). Muestra el formulario para subir el archivo.
@app.route('/')
def index():
    """Renderiza la página de inicio (index.html)."""
    return render_template('index.html')

# Ruta para procesar el archivo ('/validar'). Se activa con el método POST.
@app.route('/validar', methods=['POST'])
def validar():
    """
    Recibe el archivo Excel, lo procesa con pandas, ejecuta las
    validaciones y renderiza la página de resultados.
    """
    # Verificamos que el formulario haya enviado un archivo
    if 'archivo_excel' not in request.files:
        return "Error: No se encontró el componente 'archivo_excel' en el formulario.", 400
    
    file = request.files['archivo_excel']
    
    # Verificamos que el usuario haya seleccionado un archivo
    if file.filename == '':
        return "Error: No se seleccionó ningún archivo.", 400

    # Si todo está en orden, procedemos a procesar
    if file:
        try:
            # Leemos las diferentes hojas del archivo Excel en memoria usando pandas
            # Usamos `header` y `index_col` para estructurar correctamente los datos
            df_isr = pd.read_excel(file, sheet_name='Calculo ISR', index_col=0, header=4)
            df_facturacion = pd.read_excel(file, sheet_name='Facturacion', header=5)
            df_resumen = pd.read_excel(file, sheet_name='RESUMEN', header=None)
            df_iva = pd.read_excel(file, sheet_name='Calculo IVA', index_col=1, header=6)

            # Ejecutamos nuestra función de validación con los datos cargados
            resultados_validacion = ejecutar_validaciones(df_isr, df_facturacion, df_resumen, df_iva)
            
            # Enviamos los resultados a la plantilla 'resultados.html' para que los muestre
            return render_template('resultados.html', resultados=resultados_validacion, nombre_archivo=file.filename)
        
        except Exception as e:
            # Si algo sale mal (ej. el Excel no tiene el formato o las hojas correctas)
            # mostramos un error detallado para facilitar la depuración.
            error_msg = f"Error al procesar el archivo. Verifique que el formato sea correcto y que contenga las hojas 'Calculo ISR', 'Facturacion', 'RESUMEN' y 'Calculo IVA'. Detalle técnico: {e}"
            return error_msg, 500
            
    return "Error inesperado durante la carga del archivo.", 500

# --- 5. Punto de Entrada para Ejecución ---
# (Esta parte es principalmente para pruebas en un entorno local)
if __name__ == '__main__':
    # Inicia la aplicación en modo de depuración para ver los errores fácilmente
    app.run(debug=True)
