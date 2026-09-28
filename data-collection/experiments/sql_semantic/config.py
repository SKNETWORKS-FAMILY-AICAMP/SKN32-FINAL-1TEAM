# -*- coding: utf-8 -*-
"""실험용 로컬 DB 접속 설정. **소스 DB 와 철저히 분리한다.**

  SQL_LAB_HOST=127.0.0.1
  SQL_LAB_PORT=3306
  SQL_LAB_USER=...
  SQL_LAB_PASSWORD=...
  SQL_LAB_DATABASE=notice_match_sql_lab

왜 이렇게까지 하나. 이 실험은 **쓰기**를 한다(테이블 생성·적재). 설정이 비었을 때 기존
`MYSQL_*`(운영 EC2)로 자동 대체되면 공용 DB에 실험 테이블이 생긴다. 그래서

  · `SQL_LAB_*` 가 하나라도 없으면 **연결을 만들지 않는다** (소스로 대체하지 않는다)
  · 호스트가 로컬이 아니면 거부한다
  · 소스와 host·port·database 가 같으면 거부한다

비밀번호와 접속 문자열은 로그·결과물에 남기지 않는다. `describe()` 는 비밀번호를 뺀 값만 준다.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared import config as pipeline_config  # noqa: E402

PREFIX = 'SQL_LAB_'
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1')
DEFAULT_DATABASE = 'notice_match_sql_lab'


class LabConfigError(RuntimeError):
    """설정이 없거나 안전 조건을 어겼을 때. 이 예외가 나면 아무것도 쓰지 않는다."""


def source_settings():
    """소스(운영) DB 설정. 비교용으로만 읽는다."""
    return {
        'host': pipeline_config.get('MYSQL_HOST', '127.0.0.1'),
        'port': int(pipeline_config.get('MYSQL_PORT', '3306') or 3306),
        'database': pipeline_config.get('MYSQL_DATABASE') or '',
    }


def lab_settings():
    """실험 DB 설정. 하나라도 없으면 LabConfigError."""
    values = {key: pipeline_config.get(PREFIX + key.upper())
              for key in ('host', 'port', 'user', 'password', 'database')}
    values['database'] = values['database'] or DEFAULT_DATABASE
    missing = [PREFIX + k.upper() for k, v in values.items()
               if k in ('host', 'user', 'password') and not v]
    if missing:
        raise LabConfigError(
            '실험 DB 설정이 없다: %s\n'
            '  .env 에 아래 다섯 줄을 추가한다 (소스 DB 설정과 별개다)\n'
            '    %sHOST=127.0.0.1\n    %sPORT=3306\n    %sUSER=...\n'
            '    %sPASSWORD=...\n    %sDATABASE=%s'
            % (', '.join(missing), PREFIX, PREFIX, PREFIX, PREFIX, PREFIX, DEFAULT_DATABASE))
    values['port'] = int(values['port'] or 3306)
    return values


def guard(lab, source=None):
    """쓰기 전에 확인한다. 문제가 있으면 LabConfigError 를 던진다."""
    source = source or source_settings()
    if str(lab['host']).strip().lower() not in LOCAL_HOSTS:
        raise LabConfigError('실험 DB 는 로컬이어야 한다. 지금 호스트: %s' % lab['host'])
    same_server = (str(lab['host']).strip().lower() == str(source['host']).strip().lower()
                   and int(lab['port']) == int(source['port']))
    if same_server and lab['database'] == source['database']:
        raise LabConfigError('실험 DB 가 소스 DB 와 같다 (%s). 다른 이름을 쓴다.' % lab['database'])
    if lab['database'] == source['database']:
        raise LabConfigError('실험 DB 이름이 소스와 같다 (%s). 다른 이름을 쓴다.' % lab['database'])
    return True


def describe(lab=None, source=None):
    """기록용. 비밀번호는 넣지 않는다."""
    lab = lab or lab_settings()
    source = source or source_settings()
    return {
        'lab': {'host': lab['host'], 'port': lab['port'],
                'database': lab['database'], 'user': lab['user']},
        'source': {'host': '(기록하지 않음)', 'database': source['database']},
        'separated': True,
    }


def connect(create_database=False):
    """실험 DB 연결. guard 를 통과해야만 연결한다."""
    import pymysql
    lab = lab_settings()
    guard(lab)
    connection = pymysql.connect(
        host=lab['host'], port=lab['port'], user=lab['user'], password=lab['password'],
        database=None if create_database else lab['database'],
        charset='utf8mb4', autocommit=False,
        sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,'
                 'ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION')
    if create_database:
        with connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE IF NOT EXISTS `%s` '
                           'CHARACTER SET utf8mb4 COLLATE utf8mb4_bin' % lab['database'])
        connection.select_db(lab['database'])
    return connection


def source_connection():
    """소스 DB 읽기 전용 연결. 이 실험은 여기에 쓰지 않는다."""
    from shared import store_mysql
    return store_mysql.connect()
