import json
import pytest
import cushman.db as db_module


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = str(tmp_path / 'test.db')
    monkeypatch.setattr(db_module, 'DB_PATH', db_path)
    db_module.init_db()

    from cushman.app import app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_get_index(client):
    r = client.get('/')
    assert r.status_code == 200
    assert b'html' in r.data.lower()


def test_post_assessment_valid(client):
    payload = {
        'scores': [2, 1, 0, 3, 1, 0, 0, 1, 2, 1],
        'total': 11,
        'severity': 'modere',
    }
    r = client.post('/api/assessments', json=payload)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert 'id' in data


def test_post_assessment_missing_field(client):
    r = client.post('/api/assessments', json={'total': 5})
    assert r.status_code == 400


def test_post_assessment_wrong_scores_length(client):
    r = client.post('/api/assessments', json={
        'scores': [1, 2, 3],
        'total': 6,
        'severity': 'leger',
    })
    assert r.status_code == 400


def test_get_assessments_empty(client):
    r = client.get('/api/assessments')
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data == []


def test_get_assessments_returns_saved(client):
    client.post('/api/assessments', json={
        'scores': [1]*9 + [1],
        'total': 10,
        'severity': 'modere',
    })
    r = client.get('/api/assessments')
    data = json.loads(r.data)
    assert len(data) == 1
    assert data[0]['total'] == 10


def test_delete_assessment_found(client):
    r = client.post('/api/assessments', json={
        'scores': [1]*10, 'total': 10, 'severity': 'modere',
    })
    assessment_id = json.loads(r.data)['id']
    r = client.delete(f'/api/assessments/{assessment_id}')
    assert r.status_code == 200
    assert json.loads(r.data) == {'deleted': True}


def test_delete_assessment_not_found(client):
    r = client.delete('/api/assessments/9999')
    assert r.status_code == 404


def test_get_assessment_by_id_found(client):
    # Save an assessment
    payload = {
        'scores': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        'total': 55,
        'severity': 'high',
    }
    r = client.post('/api/assessments', json=payload)
    assert r.status_code == 201
    data = json.loads(r.data)
    assessment_id = data['id']

    # Fetch it by ID
    r = client.get(f'/api/assessments/{assessment_id}')
    assert r.status_code == 200
    assessment = json.loads(r.data)
    assert assessment['id'] == assessment_id
    assert assessment['total'] == 55
    assert assessment['severity'] == 'high'
    assert assessment['scores'] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_get_assessment_by_id_not_found(client):
    r = client.get('/api/assessments/9999')
    assert r.status_code == 404
    data = json.loads(r.data)
    assert data['error'] == 'not found'