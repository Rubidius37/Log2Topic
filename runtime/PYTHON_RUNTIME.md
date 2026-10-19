# 내장 Python 실행 환경

Log2Topic 배포본에는 공식 CPython 3.13.15의 Windows x64 임베디드 패키지가 포함됩니다. 별도의 Python 설치나 PATH 설정은 필요하지 않습니다.

- 원본: https://www.python.org/downloads/release/python-31315/
- 압축 파일: `python-3.13.15-embed-amd64.zip`
- SHA-256: `D1F04D990AEE1253D8569E8E5104E30FA9F5FA830899F14843448872D936A2CF`

처음 실행할 때 압축 파일을 로컬 `runtime/python/`에 풉니다. 공식 압축 파일 안에는 `LICENSE.txt`가 포함되어 있으며, 풀린 `runtime/python/` 폴더는 자동 생성물이므로 Git에서 추적하지 않습니다.
