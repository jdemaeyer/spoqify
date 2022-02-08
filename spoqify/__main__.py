from spoqify.utils import load_dotenv


if __name__ == '__main__':
    load_dotenv()
    from spoqify.app import app
    app.run()
