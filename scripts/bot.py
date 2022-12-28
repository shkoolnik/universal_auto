import os
import time
import csv
import datetime
import pendulum
import sys
import redis
import re
import html
import json
import time
import logging
import traceback
from telegram import * 
from telegram.ext import *
from app.models import *
from . import bolt, uklon, uber
from scripts.driversrating import DriversRatingMixin
import traceback
import hashlib
from django.db import IntegrityError

PORT = int(os.environ.get('PORT', '8443'))
DEVELOPER_CHAT_ID = 803129892

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.DEBUG)
logger = logging.getLogger(__name__)

processed_files = []

#Ordering taxi

def start(update, context):
    update.message.reply_text('Привіт! Тебе вітає Універсальне таксі - викликай кнопкою нижче.')
    chat_id = update.message.chat.id
    user = User.get_by_chat_id(chat_id)
    keyboard = [KeyboardButton(text="\U0001f4f2 Надати номер телефону", request_contact=True),
                KeyboardButton(text="\U0001f696 Викликати Таксі", request_location=True),
                KeyboardButton(text="\U0001f465 Надати повну інформацію"),
                KeyboardButton(text="\U0001f4e2 Залишити відгук")]
    if user:
        user.chat_id = chat_id
        user.save()
        if user.phone_number:
           keyboard = [keyboard[1], keyboard[2], keyboard[3]]
        reply_markup = ReplyKeyboardMarkup(
          keyboard=[keyboard],
          resize_keyboard=True,
        )
    else:
        User.objects.create(chat_id=chat_id)
        reply_markup = ReplyKeyboardMarkup(
          keyboard=[keyboard],
          resize_keyboard=True,
        )
    update.message.reply_text("Будь ласка розшарьте номер телефону та геолокацію для виклику таксі", reply_markup=reply_markup,)

def update_phone_number(update, context):
    chat_id = update.message.chat.id
    user = User.get_by_chat_id(chat_id)
    phone_number = update.message.contact.phone_number
    if (phone_number and user):
        user.phone_number = phone_number
        user.chat_id = chat_id
        user.save()
        update.message.reply_text('Дякуємо ми отримали ваш номер телефону для звязку з водієм')

LOCATION_WRONG = "Місце посадки - невірне"
LOCATION_CORRECT = "Місце посадки - вірне"

def location(update: Update, context: CallbackContext):
    active_drivers = [i.chat_id for i in Driver.objects.all() if i.driver_status == f'{Driver.ACTIVE}']

    if len(active_drivers) == 0:
        report = update.message.reply_text('Вибачте, але зараз немає вільний водіїв. Скористайтеся послугою пізніше')
        return report
    else:
        if update.edited_message:
            m = update.edited_message
        else:
            m = update.message
        m = context.bot.sendLocation(update.effective_chat.id, latitude=m.location.latitude,
                                     longitude=m.location.longitude, live_period=600)


        context.user_data['latitude'], context.user_data['longitude'] = m.location.latitude, m.location.longitude
        context.user_data['from_address'] = 'Null'
        the_confirmation_of_location(update, context)

        for i in range(1, 10):
            try:
                logger.error(i)
                m = context.bot.editMessageLiveLocation(m.chat_id, m.message_id, latitude=i * 10, longitude=i * 10)
                print(m)
            except Exception as e:
                logger.error(msg=e.message)
                logger.error(i)
            time.sleep(5)

STATE = None
LOCATION, FROM_ADDRESS, TO_THE_ADDRESS, COMMENT, NAME, SECOND_NAME, EMAIL = range(1, 8)

def the_confirmation_of_location(update, context):
    global STATE
    STATE = LOCATION

    keyboard = [KeyboardButton(text=f"\u2705 {LOCATION_CORRECT}"),
                KeyboardButton(text=f"\u274c {LOCATION_WRONG}")]

    reply_markup = ReplyKeyboardMarkup(
        keyboard=[keyboard],
        resize_keyboard=True, )

    update.message.reply_text('Виберіть статус вашої геолокації!', reply_markup=reply_markup)

def from_address(update, context):
    global STATE
    STATE = FROM_ADDRESS
    context.user_data['latitude'], context.user_data['longitude'] = 'Null', 'Null'
    update.message.reply_text('Введіть адресу місця посадки:', reply_markup=ReplyKeyboardRemove())

def to_the_adress(update, context):
    global STATE
    if STATE == FROM_ADDRESS:
        context.user_data['from_address'] = update.message.text
        STATE = TO_THE_ADDRESS
    update.message.reply_text('Введіть адресу місця призначення:', reply_markup=ReplyKeyboardRemove())
    STATE = TO_THE_ADDRESS

def payment_method(update, context):
    global STATE
    STATE = None
    context.user_data['to_the_address'] = update.message.text

    keyboard = [KeyboardButton(text=f"\U0001f4b7 {Order.CASH}"),
                KeyboardButton(text=f"\U0001f4b8 {Order.CARD}")]

    reply_markup = ReplyKeyboardMarkup(
        keyboard=[keyboard],
        resize_keyboard=True, )

    update.message.reply_text('Виберіть спосіб оплати:', reply_markup=reply_markup)

def order_create(update, context):
    WAITING = 'Очікується'

    payment_method = update.message.text
    chat_id = update.message.chat.id
    user = User.get_by_chat_id(chat_id)

    order = Order.objects.create(
        from_address=context.user_data['from_address'],
        latitude=context.user_data['latitude'],
        longitude=context.user_data['longitude'],
        to_the_address=context.user_data['to_the_address'],
        phone_number=user.phone_number,
        chat_id_client=chat_id,
        sum='',
        payment_method=payment_method.split()[1],
        status_order=WAITING)

    order.save()
    update.message.reply_text('Ваша заявка прийнята')


# Changing status of driver

def status(update, context):
    chat_id = update.message.chat.id
    driver = Driver.get_by_chat_id(chat_id)
    if True:
        buttons = [ [KeyboardButton(Driver.ACTIVE)],
                    [KeyboardButton(Driver.WITH_CLIENT)],
                    [KeyboardButton(Driver.WAIT_FOR_CLIENT)],
                    [KeyboardButton(Driver.OFFLINE)]
                ]

        context.bot.send_message(chat_id=update.effective_chat.id, text='Оберіть статус',
                                 reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True))
    else:
        update.message.reply_text("Ви не в списку водіїв автопарку")

def set_status(update, context):
    status = update.message.text
    chat_id = update.message.chat.id
    driver = Driver.get_by_chat_id(chat_id)
    if driver is not None:
        driver.driver_status = status
        driver.save()
        update.message.reply_text(f'Твій статус: <b>{status}</b>', reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
    else:
        update.message.reply_text(f'Зареєструся як водій', reply_markup=ReplyKeyboardRemove())

# Sending comment
def comment(update, context):
    global STATE
    STATE = COMMENT
    update.message.reply_text('Залишіть відгук або сповістіть о проблемі', reply_markup=ReplyKeyboardRemove())

def save_comment(update, context):
    global STATE
    context.user_data['comment'] = update.message.text
    chat_id = update.message.chat.id

    order = Comment.objects.create(
                comment=context.user_data['comment'],
                chat_id=chat_id)
    order.save()

    STATE = None
    update.message.reply_text('Ваш відгук був збережено. Очікуйте, менеджер скоро з вами звяжеться!')

# Getting id for users
def get_id(update, context):
    chat_id = update.message.chat.id
    update.message.reply_text(f"Ваш id: {chat_id}")

# Adding information for Users
def name(update, context):
    global STATE
    STATE = NAME
    update.message.reply_text("Введіть ваше Ім`я:")

def second_name(update, context):
    global STATE
    STATE = SECOND_NAME
    name = update.message.text
    name = User.name_and_second_name_validator(name=name)
    if name is not None:
        context.user_data['name'] = name
        update.message.reply_text("Введіть ваше Прізвище:")
    else:
        update.message.reply_text('Ваше Ім`я занадто довге. Спробуйте ще раз')

def email(update, context):
    global STATE
    STATE = EMAIL
    second_name = update.message.text
    second_name = User.name_and_second_name_validator(name=second_name)
    if second_name is not None:
        context.user_data['second_name'] = second_name
        update.message.reply_text("Введіть вашу електронну адресу:")
    else:
        update.message.reply_text('Ваше Прізвище занадто довге. Спробуйте ще раз')

def update_data_for_user(update, context):
    global STATE
    email = update.message.text
    chat_id = update.message.chat.id
    email = User.email_validator(email=email)
    if email is not None:
        user = User.get_by_chat_id(chat_id)
        user.name, user.second_name, user.email = context.user_data['name'], context.user_data['second_name'], email
        user.save()
        update.message.reply_text('Ваші дані оновлені')
        STATE = None
    else:
        update.message.reply_text('Ваша електронна адреса некоректна. Спробуйте ще раз')


def text(update, context):
    global STATE

    if STATE is not None:
        if STATE == FROM_ADDRESS:
            return to_the_adress(update, context)
        elif STATE == TO_THE_ADDRESS:
            return payment_method(update, context)
        elif STATE == COMMENT:
            return save_comment(update, context)
        elif STATE == NAME:
            return second_name(update, context)
        elif STATE == SECOND_NAME:
            return email(update, context)
        elif STATE == EMAIL:
            return update_data_for_user(update, context)


def report(update, context):
    update.message.reply_text("Введіть ваш Uber OTP код з SMS:")
    update.message.reply_text(get_report())


#Need fix
def code(update: Update, context: CallbackContext):
    r = redis.Redis.from_url(os.environ["REDIS_URL"])
    r.publish('code', update.message.text)
    update.message.reply_text('Generating a report...')
    context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=ChatAction.TYPING)

def help(update, context) -> str:
    update.message.reply_text('''For first step make registration by, or autorizate by /start command, if already registered.
    after all you can update your report, or pull statistic for choice''')


def update_db(update, context):
    """Pushing data to database from weekly_csv files"""
    # getting and opening files
    directory = '../app'
    files = os.listdir(directory)

    UberPaymentsOrder.download_weekly_report()
    UklonPaymentsOrder.download_weekly_report()
    BoltPaymentsOrder.download_weekly_report()

    files = os.listdir(directory)
    files_csv = filter(lambda x: x.endswith('.csv'), files)
    list_new_files = list(set(files_csv)-set(processed_files))

    if len(list_new_files) == 0:
        update.message.reply_text('No new updates yet')
    else:
        update.message.reply_text('Please wait')
        for name_file in list_new_files:
            processed_files.append(name_file)
            with open(f'{directory}/{name_file}', encoding='utf8') as file:
                if 'Куцко - Income_' in name_file:
                    UklonPaymentsOrder.parse_and_save_weekly_report_to_database(file=file)
                elif '-payments_driver-___.csv' in name_file:
                    UberPaymentsOrder.parse_and_save_weekly_report_to_database(file=file)
                elif 'Kyiv Fleet 03_232 park Universal-auto.csv' in name_file:
                    BoltPaymentsOrder.parse_and_save_weekly_report_to_database(file=file)

        FileNameProcessed.save_filename_to_db(processed_files)
        list_new_files.clear()
        update.message.reply_text('Database updated')


def save_reports(update, context):
    wrf = WeeklyReportFile()
    wrf.save_weekly_reports_to_db()
    update.message.reply_text("Reports have been saved")


def error_handler(update: object, context: CallbackContext) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f'An exception was raised while handling an update\n'
        f'<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}'
        '</pre>\n\n'
        f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n'
        f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n'
        f'<pre>{html.escape(tb_string)}</pre>'
    )

    # Finally, send the message
    context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML)


def get_owner_today_report(update, context) -> str:
    pass


def get_driver_today_report(update, context) -> str:
    driver_first_name = User.objects.filter(user_id = {update.message.chat.id})
    driver_ident = PaymentsOrder.objects.filter(driver_uuid='')
    if user.type == 0:
        data = PaymentsOrder.objects.filter(transaction_time = date.today(), driver_uuid = {driver_ident} )
        update.message.reply_text(f'Hi {update.message.chat.username} driver')
        update.message.reply_text(text = data)


def get_driver_week_report(update, context) -> str:
    pass


def choice_driver_option(update, context) -> list:
        update.message.reply_text(f'Hi {update.message.chat.username} driver')
        buttons = [[KeyboardButton('Get today statistic')], [KeyboardButton('Choice week number')],[KeyboardButton('Update report')]]
        context.bot.send_message(chat_id=update.effective_chat.id, text='choice option',
        reply_markup=ReplyKeyboardMarkup(buttons))


def get_manager_today_report(update, context) -> str:
    if user.type == 1:
        data = PaymentsOrder.objects.filter(transaction_time = date.today())
        update.message.reply_text(text=data)
    else:
        error_handler()


def get_stat_for_manager(update, context) -> list:
        update.message.reply_text(f'Hi {update.message.chat.username} manager')
        buttons = [[KeyboardButton('Get all today statistic')]]
        context.bot.send_message(chat_id=update.effective_chat.id, text='choice option',
        reply_markup=ReplyKeyboardMarkup(buttons))


def drivers_rating(update, context):
    text = 'Drivers Rating\n\n'
    for fleet in DriversRatingMixin().get_rating():
        text += fleet['fleet'] + '\n'
        for period in fleet['rating']:
            text += f"{period['start']:%d.%m.%Y} - {period['end']:%d.%m.%Y}" + '\n'
            if period['rating']:
                text += '\n'.join([f"{item['num']} {item['driver']} {item['amount']:15.2f} - {item['trips'] if item['trips']>0 else ''}" for item in period['rating']]) + '\n\n'
            else:
                text += 'Receiving data...Please try later\n'
    update.message.reply_text(text)


def aut_handler(update, context) -> list:
    if 'Get autorizate' in update.message.text:
        if user.type == 0:
            choice_driver_option(update, context)
        elif user.type == 2:
            get_owner_today_report(update, context)
        elif user.type == 1:
            get_stat_for_manager(update, context)
        else:
            update_phone_number()


def get_update_report(update, context):
    user = User.get_by_chat_id(chat_id)
    if user in uklon_drivers_list:
        uklon.run()
        aut_handler(update, context)
    elif username in bolt_drivers_list:
        bolt.run()
        aut_handler(update, context)
    elif username in uber_drivers_list:
        update.message.reply_text("Enter you Uber OTP code from SMS:")
        uber.run()
        aut_handler(update, context)



STATUS, LICENCE_PLACE = range(2)


def status_car(update, context):
    chat_id = update.message.chat.id
    driver = Driver.get_by_chat_id(chat_id)
    if driver is not None:
        buttons = [[KeyboardButton('Serviceable')], [KeyboardButton('Broken')]]
        context.bot.send_message(chat_id=update.effective_chat.id, text='Choice your status of car',
                                        reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True))
    else:
        update.message.reply_text('This command only for driver')
        return ConversationHandler.END
    return STATUS


def numberplate(update, context):
    context.user_data[STATUS] = update.message.text
    update.message.reply_text('Please, enter the number of your car that broke down', reply_markup=ReplyKeyboardRemove())
    return LICENCE_PLACE


def change_status_car(update, context):
    """This func change status_car and only for the role of drivers"""
    chat_id = update.message.chat.id
    context.user_data[LICENCE_PLACE] = update.message.text.upper()
    number_car = context.user_data[LICENCE_PLACE]
    status_car = context.user_data[STATUS]
    queryset = Vehicle.objects.all()
    numberplates = [i.licence_plate for i in queryset]
    if number_car in numberplates:
        driver = Driver.get_by_chat_id(chat_id)
        vehicle = Vehicle.get_by_numberplate(number_car)
        vehicle.car_status = status_car
        vehicle.save()
        numberplates.clear()
        update.message.reply_text('Your status of car has been changed')
    else:
        update.message.reply_text('This number is not in the database or incorrect data was sent. Contact the manager or repeat the command')

    return ConversationHandler.END


def cancel_status_car(update: Update, context: CallbackContext):
    """ Cancel the entire dialogue process. Data will be lost
    """
    update.message.reply_text('Cancel. To start from scratch press /status_car')
    return ConversationHandler.END



NUMBERPLATE, PHOTO, START_OF_REPAIR, END_OF_REPAIR = range(4)


def numberplate_car(update, context):
    chat_id = update.message.chat.id
    manager = ServiceStationManager.get_by_chat_id(chat_id)
    if manager is not None:
        update.message.reply_text('Please enter numberplate car ')
    else:
        update.message.reply_text('This commands only for service station manager')
        return ConversationHandler.END
    return NUMBERPLATE


def photo(update, context):
    context.user_data[NUMBERPLATE] = update.message.text.upper()
    queryset = Vehicle.objects.all()
    numberplates = [i.licence_plate for i in queryset]
    if context.user_data[NUMBERPLATE] not in numberplates:
        update.message.reply_text('The number you wrote is not in the database, contact the park manager')
        return ConversationHandler.END
    update.message.reply_text('Please, send me report  photo on repair (One photo)')
    return PHOTO


def start_of_repair(update, context):
    context.user_data[PHOTO] = update.message.photo[-1].get_file()
    update.message.reply_text('Please, enter date and time start of repair in format: %Y-%m-%d %H:%M:%S')
    return START_OF_REPAIR


def end_of_repair(update, context):
    context.user_data[START_OF_REPAIR] = update.message.text + "+00"
    try:
        time.strptime(context.user_data[START_OF_REPAIR], "%Y-%m-%d %H:%M:%S+00")
    except ValueError:
        update.message.reply_text('Invalid date')
        return ConversationHandler.END
    update.message.reply_text("Please, enter date and time end of repair in format: %Y-%m-%d %H:%M:%S")
    return END_OF_REPAIR


def send_report_to_db_and_driver(update, context):
    context.user_data[END_OF_REPAIR] = update.message.text + '+00'
    try:
        time.strptime(context.user_data[END_OF_REPAIR], "%Y-%m-%d %H:%M:%S+00")
    except ValueError:
        update.message.reply_text('Invalid date')
        return ConversationHandler.END
    order = RepairReport(
                    repair=context.user_data[PHOTO]["file_path"],
                    numberplate=context.user_data[NUMBERPLATE],
                    start_of_repair=context.user_data[START_OF_REPAIR],
                    end_of_repair=context.user_data[END_OF_REPAIR])
    order.save()
    update.message.reply_text('Your report saved to database')
    #vehicle = Vehicle.get_by_numberplate(context.user_data[NUMBERPLATE])
    #chat_id_driver = vehicle.driver.chat_id
    #context.bot.send_message(chat_id=chat_id_driver, text=f'Your car {context.user_data[NUMBERPLATE]} renovated')
    return ConversationHandler.END


def cancel_send_report(update, context):
    update.message.reply_text('/cancel. To start from scratch press /send_report')
    return ConversationHandler.END


def broken_car(update, context):
    chat_id = update.message.chat.id
    driver_manager = DriverManager.get_by_chat_id(chat_id)
    if driver_manager is not None:
        vehicle = Vehicle.objects.filter(car_status='Broken')
        report = ''
        result = [f'{i.licence_plate}' for i in vehicle]
        if len(result) == 0:
            update.message.reply_text("No broken cars")
        else:
            for i in result:
                report += f'{i}\n'
            update.message.reply_text(f'{report}')
    else:
        update.message.reply_text('This commands only for service station manager')


def get_information(update, context):
    chat_id = update.message.chat.id
    driver_manager = DriverManager.get_by_chat_id(chat_id)
    driver = Driver.get_by_chat_id(chat_id)
    manager = ServiceStationManager.get_by_chat_id(chat_id)
    if driver is not None:
        report = '/status - changing status of driver\n' \
                 '/status_car -changing status of car'
        update.message.reply_text(f'{report}')
    elif driver_manager is not None:
        report = '/broken_car - showing all broken car\n' \
                 '/status - showing status  of drivers\n'
        update.message.reply_text(f'{report}')
    elif manager is not None:
        report = '/send_report - sending report of repair\n'
        update.message.reply_text(f'{report}')
    else:
        update.message.reply_text('There is no information on commands for your role yet')


def main():
    updater = Updater(os.environ['TELEGRAM_TOKEN'], use_context=True)
    dp = updater.dispatcher

    # Geting id for users
    dp.add_handler(CommandHandler("id", get_id))

    # Changing status of driver
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(MessageHandler(
        Filters.text(Driver.ACTIVE) |
        Filters.text(Driver.WITH_CLIENT) |
        Filters.text(Driver.WAIT_FOR_CLIENT) |
        Filters.text(Driver.OFFLINE),
        set_status))

    # Ordering taxi
    dp.add_handler(CommandHandler("start", start))
    #incomplete auth
    dp.add_handler(MessageHandler(Filters.contact, update_phone_number))
    # ordering taxi
    dp.add_handler(MessageHandler(Filters.location, location, run_async=True))
    dp.add_handler(MessageHandler(Filters.text(f"\u2705 {LOCATION_CORRECT}"), to_the_adress))
    dp.add_handler(MessageHandler(Filters.text(f"\u274c {LOCATION_WRONG}"), from_address))
    dp.add_handler(MessageHandler(
        Filters.text(f"\U0001f4b7 {Order.CASH}") |
        Filters.text(f"\U0001f4b8 {Order.CARD}"),
        order_create))
    # sending comment
    dp.add_handler(MessageHandler(Filters.text("\U0001f4e2 Залишити відгук"), comment))
    # updating information for Users
    dp.add_handler(MessageHandler(Filters.text("\U0001f465 Надати повну інформацію"), name))

    dp.add_handler(MessageHandler(Filters.text, text))


    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('status_car', status_car),
        ],
        states={
            STATUS: [
                MessageHandler(Filters.all, numberplate, pass_user_data=True),
            ],
            LICENCE_PLACE: [
                MessageHandler(Filters.all, change_status_car, pass_user_data=True),
                CommandHandler('cancel', cancel_status_car)
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_status_car),
        ],
    )

    conv_handler_1 = ConversationHandler(
        entry_points=[
            CommandHandler('send_report', numberplate_car),
        ],
        states={
            NUMBERPLATE: [
                MessageHandler(Filters.all, photo, pass_user_data=True),
            ],
            PHOTO: [
                MessageHandler(Filters.all, start_of_repair, pass_user_data=True),
            ],
            START_OF_REPAIR: [
                MessageHandler(Filters.all, end_of_repair, pass_user_data=True),
            ],
            END_OF_REPAIR: [
                MessageHandler(Filters.all, send_report_to_db_and_driver, pass_user_data=True),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_send_report),
        ],
    )



    dp.add_handler(CommandHandler("help",   help))

    dp.add_handler(CommandHandler("report", report, run_async=True))



    dp.add_handler(MessageHandler(Filters.regex(r'^\d{4}$'), code))
    dp.add_error_handler(error_handler)


    dp.add_handler(CommandHandler('update', update_db, run_async=True))
    dp.add_handler(CommandHandler("save_reports", save_reports))
    dp.add_handler(CommandHandler("rating", drivers_rating))
    dp.add_handler(CommandHandler("broken_car", broken_car))
    dp.add_handler(CommandHandler("get_information", get_information))
    dp.add_handler(MessageHandler(Filters.text('Get all today statistic'), get_manager_today_report))
    dp.add_handler(MessageHandler(Filters.text('Get today statistic'), get_driver_today_report))
    dp.add_handler(MessageHandler(Filters.text('Choice week number'), get_driver_week_report))
    dp.add_handler(MessageHandler(Filters.text('Update report'), get_update_report))
    
        
    updater.start_polling()
    updater.idle()


def run():
    main()
