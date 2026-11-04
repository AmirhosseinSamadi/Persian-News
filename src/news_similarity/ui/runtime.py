from news_similarity.ui.services.ui_facade import UiConfig, UiFacade


def get_facade():
    return UiFacade(UiConfig.from_environment())
