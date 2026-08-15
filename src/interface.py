import sys
from tkinter import Tk, ttk, messagebox


def launch_interface():
    root = Tk()
    root.title("Tech Video AI")
    root.geometry("440x440")
    root.minsize(440, 440)
    root.resizable(False, False)

    title = ttk.Label(root, text="Gerador de Vídeo Tech", font=("Segoe UI", 16, "bold"))
    title.pack(pady=(18, 10))

    ttk.Label(root, text="Tema do vídeo:").pack(anchor="w", padx=20)
    tema_var = ttk.Entry(root, width=45)
    tema_var.pack(padx=20, pady=(0, 10), fill="x")

    ttk.Label(root, text="Duração em segundos:").pack(anchor="w", padx=20)
    duracao_var = ttk.Entry(root, width=20)
    duracao_var.pack(anchor="w", padx=20, pady=(0, 10))

    idioma_var = ttk.Combobox(root, values=["pt", "es", "en"], state="readonly", width=18)
    idioma_var.set("pt")
    ttk.Label(root, text="Idioma:").pack(anchor="w", padx=20)
    idioma_var.pack(anchor="w", padx=20, pady=(0, 10))

    modo_var = ttk.Combobox(root, values=["short", "long"], state="readonly", width=18)
    modo_var.set("short")
    ttk.Label(root, text="Formato:").pack(anchor="w", padx=20)
    modo_var.pack(anchor="w", padx=20, pady=(0, 14))

    def gerar():
        tema = tema_var.get().strip()
        duracao = duracao_var.get().strip()
        modo = modo_var.get()
        idioma = idioma_var.get()

        if not tema:
            messagebox.showerror("Campo obrigatório", "Informe o tema do vídeo.")
            return

        try:
            if duracao:
                int(duracao)
        except ValueError:
            messagebox.showerror("Valor inválido", "A duração deve ser um número inteiro em segundos.")
            return

        from main import run_generation
        import argparse

        args = argparse.Namespace(
            tema=tema,
            idioma=idioma,
            upload=False,
            batch=None,
            test=True,
            modo=modo,
            duracao=int(duracao) if duracao else None,
            gui=False,
        )

        ok = run_generation(args)
        if ok:
            messagebox.showinfo("Sucesso", "Vídeo gerado com sucesso!")
            root.destroy()
        else:
            messagebox.showerror("Erro", "O processo falhou. Verifique o console.")

    btn = ttk.Button(root, text="Gerar vídeo", command=gerar)
    btn.pack(pady=(8, 16))

    root.mainloop()


if __name__ == "__main__":
    launch_interface()
