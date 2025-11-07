import pandas as pd
import matplotlib.pyplot as plt

DB_FILE = 'complaints_db.jsonl' # Бот сақтайтын файл

def create_visuals():
    print("Дашбордты жаңарту басталды...")
    try:
        # JSONL файлын оқу
        analysis_df = pd.read_json(DB_FILE, lines=True)
        # Кортежді қалыпқа келтіру
        analysis_df = pd.concat([analysis_df.drop(['tuple'], axis=1), 
                                 analysis_df['tuple'].apply(pd.Series)], axis=1)
    except ValueError:
        print(f"'{DB_FILE}' файлы бос немесе деректер жоқ.")
        return
    except FileNotFoundError:
        print(f"'{DB_FILE}' файлы табылмады. Алдымен бот арқылы шағым жіберіңіз.")
        return

    # --- 3. Визуализация (Суреттерді сақтау) ---
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
    plt.figure(figsize=(10, 6))

    # 1. Ең проблемалық маршруттар
    routes_counts = analysis_df['Объект'].value_counts().nlargest(10)
    routes_counts.plot(kind='bar', color='skyblue')
    plt.title('Ең проблемалық маршруттар')
    plt.ylabel('Шағымдар саны')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig('dashboard_routes.png')
    print("График 'dashboard_routes.png' сақталды.")
    plt.clf()

    # 2. Шағым деңгейлері
    priority_counts = analysis_df['priority'].value_counts()
    priority_counts.plot(kind='pie', autopct='%1.1f%%', labels=priority_counts.index)
    plt.title('Шағымдарды деңгейі бойынша бөлу')
    plt.ylabel('')
    plt.tight_layout()
    plt.savefig('dashboard_priority.png')
    print("График 'dashboard_priority.png' сақталды.")
    plt.clf()

    # 3. Аспектілер жиілігі
    aspect_counts = analysis_df['Аспект'].value_counts()
    aspect_counts.plot(kind='bar', color='lightgreen')
    plt.title('Шағым аспектілерінің жиілігі')
    plt.ylabel('Шағымдар саны')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig('dashboard_aspects.png')
    print("График 'dashboard_aspects.png' сақталды.")

    print("\nЖаңарту аяқталды! 'dashboard_*.png' файлдарын Tilda-ға жүктеңіз.")

if __name__ == "__main__":
    create_visuals()