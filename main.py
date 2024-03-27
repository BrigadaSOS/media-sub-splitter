import os
import subprocess

# Ruta de la carpeta con los archivos MKV
carpeta_origen = './input'

# Obtener la lista de archivos MKV en la carpeta
archivos_mkv = [archivo for archivo in os.listdir(carpeta_origen) if archivo.endswith('.mkv')]

# Directorio de salida para los archivos convertidos
carpeta_destino = './output'

# Comando de conversión FFmpeg
# comando_ffmpeg = 'ffmpeg -i "{input}" -c:v libx265 -crf 23 -c:a copy "{output}"'
# Comando para eliminar un track especifico
comando_ffmpeg = 'ffmpeg -i "{input}" -map 0 -map -0:a:0 -map -0:a:1 -map -0:a:2 -map -0:a:3 -c:v copy -c:a copy -c:s copy "{output}"'


# Iterar a través de los archivos MKV y convertirlos
for archivo_mkv in archivos_mkv:
    nombre_base, extension = os.path.splitext(archivo_mkv)
    archivo_salida = f"{nombre_base}_v2.mkv"
    
    ruta_entrada = os.path.join(carpeta_origen, archivo_mkv)
    ruta_salida = os.path.join(carpeta_destino, archivo_salida)
    
    comando = comando_ffmpeg.format(input=ruta_entrada, output=ruta_salida)
    
    # Ejecutar el comando FFmpeg
    subprocess.call(comando, shell=True)

print("Conversión completada.")
