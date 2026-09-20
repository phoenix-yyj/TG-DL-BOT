import speedtest
import time
from datetime import datetime
import asyncio
from .i18n import tr

SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

def get_readable_file_size(size_in_bytes):
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    return f'{round(size_in_bytes, 2)}{SIZE_UNITS[min(index, len(SIZE_UNITS)-1)]}'

def speed_convert(size, byte=True):
    if not byte:
        size = size / 8
    units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
    power = 1024
    index = 0
    while size > power and index < len(units)-1:
        size /= power
        index += 1
    return f"{round(size, 2)} {units[index]}"

async def run_speedtest(client=None, message=None):
    if client and message:
        try:
            status_msg = await message.reply_text(tr(message, "speed_testing"))
        except Exception as e:
            print(f"Failed to send initial message: {e}")
            return None
    
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        
        best = st.results.server
        server_info = f"🌍 {best['sponsor']} ({best['name']}, {best['country']})"
        
        if client and message:
            await status_msg.edit_text(tr(message, "speed_best_server", server=server_info))
        
        download = st.download()
        if client and message:
            await status_msg.edit_text(tr(message, "speed_uploading"))
        upload = st.upload()
        
        st.results.share()
        result = st.results.dict()
        
        results_text = tr(message, "speed_result", download=speed_convert(result['download'], False),
                          upload=speed_convert(result['upload'], False), ping=result['ping'],
                          sent=get_readable_file_size(result['bytes_sent']),
                          received=get_readable_file_size(result['bytes_received']), timestamp=result['timestamp'],
                          server_name=result['server']['name'], server_country=result['server']['country'],
                          sponsor=result['server']['sponsor'], latency=result['server']['latency'],
                          ip=result['client']['ip'], country=result['client']['country'], isp=result['client']['isp'],
                          rating=result['client'].get('isprating', '无'), share=result['share'] or '无')
        
        # Clean up status message
        if client and message:
            try:
                await status_msg.delete()
            except Exception:
                pass
            
        return results_text

    except Exception as e:
        error_msg = tr(message, "speed_error", error=str(e))
        if client and message:
            try:
                await message.reply_text(error_msg)
            except Exception as reply_error:
                print(f"Failed to send error message: {reply_error}")
        else:
            print(error_msg)
        return None

async def main():
    await run_speedtest()

if __name__ == "__main__":
    asyncio.run(main())
