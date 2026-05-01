      FUNCTION RAN3(IDUM)
C----------------------------------------------------------------------+
C  Returns a uniform random deviate between 0.0 and 1.0.  Set idum to
C  any negative value to initialize or reinitialize the sequence.
C  According to Knuth, any large MBIG, and any smaller (but still large)
C  can be substituted for the value of parameters.
C----------------------------------------------------------------------+
      INTEGER IDUM
      INTEGER MBIG, MSEED, MZ 
      REAL RAN3, FAC
      PARAMETER (MBIG=1000000000, MSEED=161803398, MZ=0, FAC=1./MBIG)
C      PARAMETER (MBIG=4000000, MSEED=1618033, MZ=0, FAC=1./MBIG)
      INTEGER I, IFF, II, INEXT, INEXTP, K
      INTEGER MJ, MK, MA(55)
      SAVE IFF, INEXT, INEXTP, MA
      DATA IFF /0/

      IF(IDUM .LT. 0 .OR. IFF .EQ. 0) THEN
         IFF = 1
         MJ = MSEED - IABS(IDUM)
         MJ = MOD(MJ, MBIG)
         MA(55) = MJ
         MK = 1
         DO I = 1, 54
            II = MOD(21*I, 55)
            MA(II) = MK
            MK = MJ - MK
            IF(MK .LT. MZ) MK = MK + MBIG
            MJ = MA(II)
         ENDDO
         DO K = 1, 4
            DO I = 1, 55
               MA(I) = MA(I) - MA(1+MOD(I+30,55))
               IF(MA(I) .LT. MZ) MA(I) = MA(I) + MBIG
            ENDDO
         ENDDO
         INEXT = INEXT + 1
         INEXTP = 31
         IDUM = 1
      ENDIF

      INEXT = INEXT + 1
      IF(INEXT .EQ. 56) INEXT = 1
      INEXTP = INEXTP + 1
      IF(INEXTP .EQ. 56) INEXTP = 1
      MJ = MA(INEXT) - MA(INEXTP)
      IF(MJ .LT. MZ) MJ = MJ + MBIG
      MA(INEXT) = MJ
      RAN3 = MJ*FAC
      RETURN
      END




      FUNCTION RAN1(IDUM)
C----------------------------------------------------------------------+
C
C  Returns a uniform random deviate between 0.0 and 1.0.  Set idum to
C  any negative value to initialize or reinitialize the sequence.
C  According to Knuth, any large MBIG, and any smaller (but still large)
C  can be substituted for the value of parameters.
C----------------------------------------------------------------------+
      INTEGER IDUM
      INTEGER MBIG, MSEED, MZ
      REAL RAN1, FAC
      PARAMETER (MBIG=1000000000, MSEED=161803398, MZ=0, FAC=1./MBIG)
C      PARAMETER (MBIG=4000000, MSEED=1618033, MZ=0, FAC=1./MBIG)
      INTEGER I, IFF, II, INEXT, INEXTP, K
      INTEGER MJ, MK, MA(55)
      SAVE IFF, INEXT, INEXTP, MA
      DATA IFF /0/

      IF(IDUM .LT. 0 .OR. IFF .EQ. 0) THEN
         IFF = 1
         MJ = MSEED - IABS(IDUM)
         MJ = MOD(MJ, MBIG)
         MA(55) = MJ
         MK = 1
         DO I = 1, 54
            II = MOD(21*I, 55)
            MA(II) = MK
            MK = MJ - MK
            IF(MK .LT. MZ) MK = MK + MBIG
            MJ = MA(II)
         ENDDO
         DO K = 1, 4
            DO I = 1, 55
               MA(I) = MA(I) - MA(1+MOD(I+30,55))
               IF(MA(I) .LT. MZ) MA(I) = MA(I) + MBIG
            ENDDO
         ENDDO
         INEXT = INEXT + 1
         INEXTP = 31
         IDUM = 1
      ENDIF

      INEXT = INEXT + 1
      IF(INEXT .EQ. 56) INEXT = 1
      INEXTP = INEXTP + 1
      IF(INEXTP .EQ. 56) INEXTP = 1
      MJ = MA(INEXT) - MA(INEXTP)
      IF(MJ .LT. MZ) MJ = MJ + MBIG
      MA(INEXT) = MJ
      RAN1 = MJ*FAC
      RETURN
      END




      FUNCTION RAN2(IDUM)
C----------------------------------------------------------------------+
C
C  Returns a uniform random deviate between 0.0 and 1.0.  Set idum to
C  any negative value to initialize or reinitialize the sequence.
C  According to Knuth, any large MBIG, and any smaller (but still large)
C  can be substituted for the value of parameters.
C----------------------------------------------------------------------+
      INTEGER IDUM
      INTEGER MBIG, MSEED, MZ
      REAL RAN2, FAC
      PARAMETER (MBIG=1000000000, MSEED=161803398, MZ=0, FAC=1./MBIG)
C      PARAMETER (MBIG=4000000, MSEED=1618033, MZ=0, FAC=1./MBIG)
      INTEGER I, IFF, II, INEXT, INEXTP, K
      INTEGER MJ, MK, MA(55)
      SAVE IFF, INEXT, INEXTP, MA
      DATA IFF /0/

      IF(IDUM .LT. 0 .OR. IFF .EQ. 0) THEN
         IFF = 1
         MJ = MSEED - IABS(IDUM)
         MJ = MOD(MJ, MBIG)
         MA(55) = MJ
         MK = 1
         DO I = 1, 54
            II = MOD(21*I, 55)
            MA(II) = MK
            MK = MJ - MK
            IF(MK .LT. MZ) MK = MK + MBIG
            MJ = MA(II)
         ENDDO
         DO K = 1, 4
            DO I = 1, 55
               MA(I) = MA(I) - MA(1+MOD(I+30,55))
               IF(MA(I) .LT. MZ) MA(I) = MA(I) + MBIG
            ENDDO
         ENDDO
         INEXT = INEXT + 1
         INEXTP = 31
         IDUM = 1
      ENDIF

      INEXT = INEXT + 1
      IF(INEXT .EQ. 56) INEXT = 1
      INEXTP = INEXTP + 1
      IF(INEXTP .EQ. 56) INEXTP = 1
      MJ = MA(INEXT) - MA(INEXTP)
      IF(MJ .LT. MZ) MJ = MJ + MBIG
      MA(INEXT) = MJ
      RAN2 = MJ*FAC
      RETURN
      END




