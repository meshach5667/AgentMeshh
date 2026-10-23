import { CTA } from '@/components/landing/CTA';
import { Features } from '@/components/landing/Features';
import { Footer } from '@/components/landing/Footer';
import { Header } from '@/components/landing/Header';
import { HeroSection } from '@/components/landing/HeroSection';
import { HowItWorks } from '@/components/landing/HowItWorks';
import { LiveStats } from '@/components/landing/LiveStats';
import { PricingSection } from '@/components/landing/PricingSection';
import { Status } from '@/components/landing/Status';

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header />
      <main className="flex-1">
        <HeroSection />
        <LiveStats />
        <Features />
        <HowItWorks />
        <PricingSection />
        <Status />
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
