import os
import sys
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Add root to sys path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

ALL_PARAMS = ["Temperature", "pH", "NH4", "TSS"]

def load_data():
    csv_path = os.path.join(PROJECT_ROOT, "data", "greenlab", "greenlab_export.csv")
    df = pd.read_csv(csv_path)
    df['fetchedAt'] = pd.to_datetime(df['fetchedAt'])
    df = df.sort_values('fetchedAt')
    df = df[df['device'] == '06M26042804']
    df.set_index('fetchedAt', inplace=True)
    df_hourly = df[ALL_PARAMS].resample('1h').mean()
    df_hourly = df_hourly.interpolate(method='linear')
    df_hourly = df_hourly.dropna()
    return df_hourly

def run_correlation():
    df = load_data()
    
    # 1. Pearson Correlation
    corr_matrix = df.corr(method='pearson')
    
    # Save text result
    with open("correlation_results.md", "w", encoding="utf-8") as f:
        f.write("# Ma trận Tương quan (Pearson)\n\n")
        f.write(corr_matrix.to_markdown())
        f.write("\n\n")
        
    print("Correlation Matrix:")
    print(corr_matrix)
    
    # 2. Heatmap
    plt.figure(figsize=(8, 6))
    sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', vmin=-1, vmax=1, fmt=".2f")
    plt.title("Pearson Correlation Heatmap - Cát Bà Station")
    plt.tight_layout()
    plt.savefig("correlation_heatmap.png", dpi=300)
    plt.close()
    
    # 3. Scatter Matrix (Pairplot)
    sns.pairplot(df, diag_kind='kde', plot_kws={'alpha': 0.5, 's': 20, 'edgecolor': 'none'})
    plt.suptitle("Scatter Matrix of Water Quality Parameters", y=1.02)
    plt.savefig("scatter_matrix.png", dpi=300)
    plt.close()
    
    print("Saved correlation_heatmap.png and scatter_matrix.png")

if __name__ == "__main__":
    run_correlation()
