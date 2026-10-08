# Обходы ошибок deliver, на которых падала первая заливка.
#
# review_attachment_file deliver зовёт ВСЕГДА, даже без вложения в опциях:
# забирает запись appStoreReviewDetail, чтобы удалить старые вложения. У
# приложения, которое ни разу не отправлялось, этой записи ещё нет, Apple
# отдаёт пустой data, и spaceship бросает «No data» — падает весь вызов,
# хотя тексты, категории и скриншоты к ревью отношения не имеют
# (CarPlay2, 8 октября 2026; fastlane/fastlane#20521, открыт с 2022).
#
# Записи нет — значит нет и вложений: удалять нечего, а своё вложение мы
# deliver не передаём. Поэтому именно этот случай пропускаем, любой другой
# сбой пробрасываем как был. Саму запись для ревью потом создаёт
# setup_app.py прямым вызовом.
require "deliver"

module Deliver
  class UploadMetadata
    alias_method :review_attachment_file_unpatched, :review_attachment_file

    def review_attachment_file(version)
      review_attachment_file_unpatched(version)
    rescue RuntimeError => error
      raise unless error.message == "No data" && options[:app_review_attachment_file].nil?

      UI.important("Записи для ревью у версии ещё нет — вложения пропускаем, " \
                   "информацию для ревью заполнит следующий шаг")
    end
  end
end
