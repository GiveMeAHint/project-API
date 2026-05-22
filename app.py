from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import numpy as np
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB_PATH = r'C:\Users\ikalm\Desktop\proj\project.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Эндпоинт список направлений (id, название)
@app.route('/api/directions', methods=['GET'])
def get_directions():
    conn = get_db()
    programs = conn.execute("SELECT id, name FROM programs ORDER BY id").fetchall()
    conn.close()
    
    return jsonify({
        'directions': [{'id': p['id'], 'name': p['name']} for p in programs]
    })

# Эндпоинт статистика по направлениям (заявления, КЦП, процент)
@app.route('/api/current_stats', methods=['GET'])
def get_current_stats():
    year = request.args.get('year')
    
    if not year:
        return jsonify({'error': 'Параметр "year" обязателен'}), 400
    
    target_year = int(year)
    conn = get_db()
    
    programs = conn.execute("SELECT id, name FROM programs").fetchall()
    
    stats = []
    for prog in programs:
        prog_id = prog['id']
        
        row = conn.execute("""
            SELECT a.app_count, q.spots 
            FROM applications a
            LEFT JOIN quotas q ON q.year = a.year AND q.program_id = a.program_id
            WHERE a.program_id = ? AND a.year = ?
        """, (prog_id, target_year)).fetchone()
        
        if row and row['app_count'] is not None and row['app_count'] > 0:
            apps = row['app_count']
            spots = row['spots'] if row['spots'] else 0
        else:
            forecast = get_median_forecast(conn, prog_id)
            if forecast:
                apps = forecast['predicted']
                spots = forecast['last_quota']
            else:
                continue  
        
        percent = round((apps / spots) * 100, 1) if spots > 0 else 0
        
        stats.append({
            'direction_id': prog_id,
            'direction_name': prog['name'],
            'applications': apps,
            'quotas': spots,
            'completion_percent': percent
        })
    
    conn.close()
    
    return jsonify({
        'year': target_year,
        'stats': stats
    })

# Эндпоинт для экрана руководства (прогноз и рекомендуемая КЦП)
@app.route('/api/forecast', methods=['POST'])
def get_forecast():
    """
    Принимает JSON:
    {
        "year": 2024,
        "direction_ids": [1, 2, 3]
    }
    Возвращает для каждого направления: прогноз заявлений и рекомендуемую КЦП
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Необходимо передать JSON'}), 400
    
    target_year = data.get('year')
    direction_ids = data.get('direction_ids')
    
    if not target_year:
        return jsonify({'error': 'Параметр "year" обязателен'}), 400
    
    if not direction_ids or not isinstance(direction_ids, list):
        return jsonify({'error': 'Параметр "direction_ids" должен быть списком'}), 400
    
    conn = get_db()
    
    results = []
    for prog_id in direction_ids:
        prog = conn.execute("SELECT name FROM programs WHERE id = ?", (prog_id,)).fetchone()
        if not prog:
            continue
        
        forecast = get_median_forecast(conn, prog_id)
        
        if forecast:
            target_ratio = 3  
            recommended_quota = int(forecast['predicted'] / target_ratio)
            
            results.append({
                'direction_id': prog_id,
                'direction_name': prog['name'],
                'predicted_applications': forecast['predicted'],
                'current_quota': forecast['last_quota'],
                'recommended_quota': max(recommended_quota, 1)
            })
    
    conn.close()
    
    return jsonify({
        'year': target_year,
        'forecasts': results
    })

# Эндпоинт для графика тренда заявлений (id названия)
@app.route('/api/trend', methods=['GET'])
def get_trend():
    """
    Принимает параметры:
    - direction_id (обязательный)
    - forecast_year (опциональный, по умолчанию 2024)
    
    Возвращает историю заявлений за 2019-2023 и прогноз на указанный год
    """
    direction_id = request.args.get('direction_id')
    forecast_year = request.args.get('forecast_year', 2024)
    
    if not direction_id:
        return jsonify({'error': 'Параметр "direction_id" обязателен'}), 400
    
    try:
        prog_id = int(direction_id)
        target_year = int(forecast_year)
    except ValueError:
        return jsonify({'error': 'Параметры должны быть целыми числами'}), 400
    
    conn = get_db()
    
    prog = conn.execute("SELECT name FROM programs WHERE id = ?", (prog_id,)).fetchone()
    if not prog:
        conn.close()
        return jsonify({'error': 'Направление не найдено'}), 404
    
    history = []
    for year in [2019, 2020, 2021, 2022, 2023]:
        row = conn.execute("""
            SELECT a.app_count, q.spots 
            FROM applications a
            LEFT JOIN quotas q ON q.year = a.year AND q.program_id = a.program_id
            WHERE a.program_id = ? AND a.year = ?
        """, (prog_id, year)).fetchone()
        
        history.append({
            'year': year,
            'applications': row['app_count'] if row and row['app_count'] else None,
            'quotas': row['spots'] if row and row['spots'] else None
        })
    
    # Получаем прогноз на запрошенный год
    forecast = get_median_forecast(conn, prog_id)
    
    conn.close()
    
    return jsonify({
        'direction_id': prog_id,
        'direction_name': prog['name'],
        'history': history,
        'forecast': {
            'year': target_year,
            'predicted_applications': forecast['predicted'] if forecast else None,
            'current_quota': forecast['last_quota'] if forecast else None
        } if forecast else None
    })

# Прогнозная модель 
def get_median_forecast(conn, program_id):
    """Прогноз методом медианы на основе истории 2019-2023"""
    history = [2019, 2020, 2021, 2022, 2023]
    ratios = []
    last_spots = 0
    
    for year in history:
        row = conn.execute("""
            SELECT a.app_count, q.spots 
            FROM applications a
            JOIN quotas q ON q.year = a.year AND q.program_id = a.program_id
            WHERE a.program_id = ? AND a.year = ? AND q.spots > 0 AND a.app_count > 0
        """, (program_id, year)).fetchone()
        
        if row:
            ratios.append(row['app_count'] / row['spots'])
            last_spots = row['spots']
    
    if len(ratios) < 2:
        return None
    
    ratio = np.median(ratios) if len(ratios) >= 3 else np.mean(ratios)
    
    quota = conn.execute("""
        SELECT spots FROM quotas
        WHERE program_id = ? AND year = 2023 AND spots > 0
    """, (program_id,)).fetchone()
    
    spots = quota['spots'] if quota else last_spots
    
    if spots <= 0:
        return None
    
    return {
        'predicted': int(ratio * spots),
        'last_quota': spots
    }

if __name__ == '__main__':
    print("API запущен на http://localhost:5000")
    print("  GET  /api/directions")
    print("  GET  /api/current_stats?year=2024")
    print("  POST /api/forecast")
    print("  GET  /api/trend?direction_id=1&forecast_year=2024")
    app.run(debug=True, host='0.0.0.0', port=5000)