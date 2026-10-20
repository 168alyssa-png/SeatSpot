"""Deterministic ordering API for map/camera regression tests only.

Real database, security and concurrency are covered by api.test.mjs and backend UI tests.
"""
import json
import uuid


def install_ordering_fixture(context):
    data = {'inventory': [dict(id=i, flavor=f, quantity_remaining=5, active=True)
                          for i, f in [('choc', 'Chocolate'), ('matcha', 'Original'), ('red', 'Red Velvet')]],
            'order': None}

    def handle(route):
        request = route.request
        if request.method == 'POST' and data['order'] is None:
            body = request.post_data_json
            item = next(i for i in data['inventory'] if i['id'] == body['cookie_id'])
            item['quantity_remaining'] -= 1
            data['order'] = dict(id=str(uuid.uuid4()), cookie_id=item['id'], cookie_flavor=item['flavor'],
                                 quantity=1, table_id=body.get('table_id'), status='New',
                                 created_at='2026-10-17T12:00:00Z')
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))
    context.route('**/api/seatspot?*', handle)
    return data
