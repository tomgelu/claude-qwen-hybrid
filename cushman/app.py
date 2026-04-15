import os
from flask import Flask, jsonify, request, send_from_directory
import cushman.db as db

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))

DB_INITIALIZED = False


@app.before_request
def ensure_db():
    global DB_INITIALIZED
    if not DB_INITIALIZED:
        db.init_db()
        DB_INITIALIZED = True


@app.get('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.post('/api/assessments')
def create_assessment():
    body = request.get_json(silent=True) or {}
    scores = body.get('scores')
    total = body.get('total')
    severity = body.get('severity')

    if scores is None or total is None or severity is None:
        return jsonify({'error': 'scores, total, and severity are required'}), 400
    if not isinstance(scores, list) or len(scores) != 10:
        return jsonify({'error': 'scores must be a list of 10 integers'}), 400

    row_id = db.save_assessment(scores, int(total), str(severity))
    return jsonify({'id': row_id}), 201


@app.get('/api/assessments')
def list_assessments():
    rows = db.get_assessments(limit=50)
    return jsonify(rows), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
