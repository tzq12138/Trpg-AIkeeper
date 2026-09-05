using System.Windows;
using System.Windows.Controls;
using ApiTestTool.Services;
using ApiTestTool.ViewModels;

namespace ApiTestTool;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
    }

    private void SaveAuth_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is MainViewModel vm)
        {
            vm.AuthManager.Save();
            vm.AuthManager.Refresh();
            MessageBox.Show("环境配置已保存。", "保存成功", MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    private void EndpointTree_SelectedItemChanged(object sender, RoutedPropertyChangedEventArgs<object> e)
    {
        if (DataContext is MainViewModel vm)
        {
            vm.EndpointTree.OnSelectedItemChanged((sender as TreeView)?.SelectedItem);
        }
    }

    private void EndpointFilter_TextChanged(object sender, TextChangedEventArgs e)
    {
        // Simple text filter: rebuild the tree items source
        if (sender is not TextBox tb) return;
        if (DataContext is not MainViewModel vm) return;

        var filter = tb.Text?.Trim().ToLower() ?? "";
        EndpointTree.ItemsSource = string.IsNullOrEmpty(filter)
            ? vm.EndpointTree.Domains
            : vm.EndpointTree.Domains; // TreeView doesn't support easy filtering; skipped for now
    }

    private void ClearHistory_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is MainViewModel vm)
            vm.History.Clear();
    }
}
